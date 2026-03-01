"""SeekingAlpha ratings spreadsheet importer.

Parses CSV or XLSX files exported from SeekingAlpha Portfolio/Quant pages.
Column names vary by export type — handled via a flexible mapping strategy.

Grade columns store SALetterGrade enum values; numeric fields are nullable floats.
Rows are upserted on (symbol_id, snapshot_date); symbols are auto-created if absent.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SALetterGrade
from app.models.sa_ratings import SARating
from app.models.symbols import Symbol

logger = logging.getLogger(__name__)

# canonical name → possible SA export column headers (case-insensitive, normalized)
_COLUMN_ALIASES: dict[str, list[str]] = {
    "ticker": ["ticker", "symbol", "stock", "equity"],
    "quant_score": ["quant_rating", "quant rating", "quant score", "quant"],
    "sa_analyst_score": [
        "sa_analyst_rating",
        "sa analyst rating",
        "analyst rating",
        "sa rating",
    ],
    "wall_st_score": [
        "wall_st_rating",
        "wall st rating",
        "wall street rating",
        "sell side rating",
    ],
    "valuation_grade": ["valuation", "valuation grade", "valuation_grade"],
    "growth_grade": ["growth", "growth grade", "growth_grade"],
    "profitability_grade": [
        "profitability",
        "profitability grade",
        "profitability_grade",
    ],
    "momentum_grade": ["momentum", "momentum grade", "momentum_grade"],
    "eps_revision_grade": [
        "eps_revisions",
        "eps revisions",
        "revisions",
        "eps revision grade",
        "eps_revision_grade",
    ],
    "div_safety_grade": [
        "dividend safety",
        "div safety",
        "div_safety",
        "div safety grade",
    ],
    "div_growth_grade": [
        "dividend growth grade",
        "div growth grade",
        "div_growth_grade",
    ],
    "div_yield_grade": [
        "dividend yield grade",
        "div yield grade",
        "div_yield_grade",
    ],
    "div_consistency_grade": [
        "dividend consistency",
        "div consistency",
        "div_consistency_grade",
    ],
    "yield_fwd": ["forward yield", "fwd yield", "dividend yield", "yield"],
    "payout_ratio": ["payout ratio", "payout"],
    "div_growth_3y": [
        "div growth 3y",
        "3y div growth",
        "dividend growth 3y",
        "div_growth_3y",
    ],
    "div_growth_5y": [
        "div growth 5y",
        "5y div growth",
        "dividend growth 5y",
        "div_growth_5y",
    ],
    "years_of_growth": [
        "years of growth",
        "dividend growth streak",
        "consecutive years",
        "years_of_growth",
    ],
    "div_frequency": [
        "frequency",
        "payment frequency",
        "div frequency",
        "div_frequency",
    ],
    "beta_24m": ["beta", "beta 24m", "24m beta", "beta_24m"],
}

_GRADE_FIELDS = frozenset(
    {
        "valuation_grade",
        "growth_grade",
        "profitability_grade",
        "momentum_grade",
        "eps_revision_grade",
        "div_safety_grade",
        "div_growth_grade",
        "div_yield_grade",
        "div_consistency_grade",
    }
)

_FLOAT_FIELDS = frozenset(
    {
        "quant_score",
        "sa_analyst_score",
        "wall_st_score",
        "yield_fwd",
        "payout_ratio",
        "div_growth_3y",
        "div_growth_5y",
        "beta_24m",
    }
)


def _normalize_col(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def _find_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    """Return the actual column name that matches any alias (case/space-insensitive)."""
    lookup = {_normalize_col(c): c for c in df.columns}
    for alias in aliases:
        key = _normalize_col(alias)
        if key in lookup:
            return lookup[key]
    return None


def _parse_grade(value: Any) -> SALetterGrade | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return SALetterGrade(s)
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s:
        return None
    is_pct = s.endswith("%")
    s = s.rstrip("%")
    try:
        v = float(s)
        return v / 100.0 if is_pct else v
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return None


def parse_sa_spreadsheet(path: str | Path) -> pd.DataFrame:
    """
    Parse a SeekingAlpha export (CSV or XLSX) into a normalized DataFrame.

    Every row has at least a ``ticker`` column.  All other columns are
    optional — missing ones are simply absent from the result.

    Raises ValueError if no ticker column can be found.
    """
    p = Path(path)
    if p.suffix.lower() in {".xlsx", ".xls"}:
        raw: pd.DataFrame = pd.read_excel(p, dtype=str)
    else:
        raw = pd.read_csv(p, dtype=str)

    # Build column rename map: raw_name → canonical_name
    rename: dict[str, str] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        found = _find_column(raw, aliases)
        if found:
            rename[found] = canonical

    if "ticker" not in rename.values():
        raise ValueError(
            f"Could not find a ticker column in {p.name}. "
            f"Columns found: {list(raw.columns)}"
        )

    df = raw.rename(columns=rename)
    canonical_present = [c for c in _COLUMN_ALIASES if c in df.columns]
    df = df[canonical_present].copy()

    df["ticker"] = df["ticker"].str.strip().str.upper()
    df = df[df["ticker"].notna() & (df["ticker"] != "")].copy()
    return df.reset_index(drop=True)


async def import_sa_ratings(
    path: str | Path,
    session: AsyncSession,
    snapshot_date: date | None = None,
) -> dict[str, Any]:
    """
    Import SA ratings from *path* into the ``sa_ratings`` table.

    Upserts on (symbol_id, snapshot_date).  Auto-creates symbols not found.

    Returns:
        {imported, skipped, errors, error_details}
    """
    if snapshot_date is None:
        snapshot_date = date.today()

    df = parse_sa_spreadsheet(path)

    results: dict[str, Any] = {
        "imported": 0,
        "skipped": 0,
        "errors": 0,
        "error_details": [],
    }

    for _, row in df.iterrows():
        ticker = str(row["ticker"]).strip().upper()

        # Resolve or auto-create symbol
        sym_row = await session.execute(select(Symbol.id).where(Symbol.ticker == ticker))
        symbol_id: int | None = sym_row.scalar_one_or_none()

        if symbol_id is None:
            sym = Symbol(ticker=ticker, asset_type="stock")
            session.add(sym)
            await session.flush()
            symbol_id = sym.id
            logger.info("Auto-created symbol for %s", ticker)

        # Build the upsert payload
        data: dict[str, Any] = {
            "symbol_id": symbol_id,
            "snapshot_date": snapshot_date,
        }

        for field in _FLOAT_FIELDS:
            if field in row:
                data[field] = _parse_float(row[field])

        for field in _GRADE_FIELDS:
            if field in row:
                grade = _parse_grade(row[field])
                # Store as string so Core insert matches the PG enum
                data[field] = grade.value if grade is not None else None

        if "years_of_growth" in row:
            data["years_of_growth"] = _parse_int(row["years_of_growth"])

        if "div_frequency" in row:
            raw_freq = row["div_frequency"]
            if raw_freq is not None and not (
                isinstance(raw_freq, float) and pd.isna(raw_freq)
            ):
                data["div_frequency"] = str(raw_freq).strip()[:20] or None

        try:
            # Exclude created_at from the update set — let server_default win on insert
            update_set = {
                k: v
                for k, v in data.items()
                if k not in ("symbol_id", "snapshot_date")
            }
            stmt = (
                pg_insert(SARating.__table__)
                .values(**data)
                .on_conflict_do_update(
                    index_elements=["symbol_id", "snapshot_date"],
                    set_=update_set,
                )
            )
            await session.execute(stmt)
            results["imported"] += 1
        except Exception as exc:
            logger.exception("Failed to import rating for %s", ticker)
            results["errors"] += 1
            results["error_details"].append({"ticker": ticker, "error": str(exc)})

    return results
