"""
Scanner API — run TA analysis pipeline on watchlist symbols.

Endpoints:
  POST /api/scanner/run               → background scan of all watchlist tickers
  GET  /api/scanner/results           → latest cached results sorted by composite_score
  GET  /api/scanner/results/{symbol}  → full detail for one ticker
  GET  /api/scanner/profiles          → list 4 scanner profiles
  POST /api/scanner/run/{symbol}      → on-demand single-ticker analysis (inline)
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.pipeline import (
    AnalysisResult,
    run_analysis_for_ticker,
    run_scanner,
)
from app.analysis.profiles import PROFILES
from app.db.session import AsyncSessionLocal, get_session
from app.models.enums import TimeframeEnum
from app.models.indicator_cache import IndicatorCache
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem
from app.schemas.scanner import (
    AnalysisMeta,
    AnalysisResponse,
    CategoryScores,
    HarmonicInfo,
    ProfileInfo,
    ScanRunResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/scanner", tags=["scanner"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_TF_MAP: dict[str, TimeframeEnum] = {
    "1d": TimeframeEnum.D1,
    "1w": TimeframeEnum.W1,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dict_to_harmonic_info(d: dict | None) -> HarmonicInfo | None:
    """Convert a cached harmonics dict to a HarmonicInfo schema object."""
    if d is None:
        return None
    return HarmonicInfo(
        detected=bool(d.get("detected", False)),
        pattern=d.get("pattern"),
        direction=d.get("direction"),
        ratio_quality=float(d.get("ratio_quality", 0.0)),
        in_prz=bool(d.get("in_prz", False)),
        prz_low=d.get("prz_low"),
        prz_high=d.get("prz_high"),
        bars_since_completion=d.get("bars_since_completion"),
    )


def _result_to_response(result: AnalysisResult, scanned_at: str = "") -> AnalysisResponse:
    meta = result.meta
    return AnalysisResponse(
        symbol=result.symbol,
        scanned_at=scanned_at or datetime.now(timezone.utc).isoformat(),
        composite_score=result.composite_score,
        category_scores=CategoryScores(**result.category_scores),
        profile_matches=result.profile_matches,
        signals=result.signals,
        meta=AnalysisMeta(
            atr=meta.get("atr", 0.0),
            atr_pct=meta.get("atr_pct", 0.0),
            last_price=meta.get("last_price", 0.0),
            volume_ratio=float(meta.get("volume_ratio", 0.0)),
            price_change_pct=float(meta.get("price_change_pct", 0.0)),
            timestamp=str(meta.get("timestamp", "")),
            bars=int(meta.get("bars", 0)),
        ),
        harmonics=_dict_to_harmonic_info(result.harmonics),
        is_actionable=result.is_actionable,
        volume_contradiction=result.volume_contradiction,
    )


def _normalize_profile_name(raw: str) -> str:
    """Normalize profile name: snake_case or CamelCase → CamelCase registry key."""
    # If it already looks CamelCase (contains uppercase), return as-is
    if any(c.isupper() for c in raw):
        return raw
    # Convert snake_case to CamelCase
    return "".join(word.capitalize() for word in re.split(r"[_\-]", raw))


async def _get_all_watchlist_symbols(db: AsyncSession) -> list[tuple[int, str]]:
    """Return all (symbol_id, ticker) pairs across all watchlists."""
    result = await db.execute(
        select(Symbol.id, Symbol.ticker)
        .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
        .where(Symbol.is_active.is_(True))
        .distinct()
    )
    return [(row[0], row[1]) for row in result.all()]


async def _run_scanner_bg(run_id: str) -> None:
    """Background task: run scanner for all watchlist symbols."""
    async with AsyncSessionLocal() as db:
        try:
            symbols = await _get_all_watchlist_symbols(db)
            if not symbols:
                log.info("Scanner run %s: no symbols found", run_id)
                return
            results = await run_scanner(symbols, db)
            await db.commit()
            log.info(
                "Scanner run %s: completed %d symbols, cached %d results",
                run_id, len(symbols), len(results),
            )
        except Exception as exc:
            log.error("Scanner run %s failed: %s", run_id, exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/run", response_model=dict[str, Any])
async def trigger_scan(
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> dict[str, Any]:
    """Trigger a full scan of all watchlist symbols (background task)."""
    symbols = await _get_all_watchlist_symbols(session)
    if not symbols:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No symbols in watchlist. Add tickers to a watchlist first.",
        )
    run_id = str(uuid.uuid4())
    background_tasks.add_task(_run_scanner_bg, run_id)
    return {
        "run_id": run_id,
        "status": "queued",
        "symbols_queued": len(symbols),
    }


@router.get("/results", response_model=list[AnalysisResponse])
async def get_latest_results(
    session: SessionDep,
    profile: Annotated[str | None, Query(description="Filter by profile name (e.g. momentum_breakout or MomentumBreakout)")] = None,
    timeframe: Annotated[str, Query(description="Timeframe: 1d or 1w")] = "1d",
) -> list[AnalysisResponse]:
    """Return latest cached analysis results sorted by composite_score descending.

    Use ?profile= to filter by matching profile name (case-insensitive, snake_case or CamelCase).
    Use ?timeframe= to select which timeframe's analysis to return (default: 1d).
    """
    tf_enum = _TF_MAP.get(timeframe, TimeframeEnum.D1)

    # Get latest full_analysis entry per symbol for the requested timeframe
    result = await session.execute(
        select(IndicatorCache)
        .where(
            IndicatorCache.indicator_name == "full_analysis",
            IndicatorCache.timeframe == tf_enum,
        )
        .order_by(desc(IndicatorCache.time))
    )
    rows = result.scalars().all()

    # Deduplicate: keep latest per symbol_id
    seen: set[int] = set()
    unique: list[IndicatorCache] = []
    for row in rows:
        if row.symbol_id not in seen:
            seen.add(row.symbol_id)
            unique.append(row)

    # Parse
    responses: list[AnalysisResponse] = []
    for row in unique:
        try:
            val = row.value
            if not isinstance(val, dict):
                continue
            meta_raw = val.get("meta", {})
            responses.append(
                AnalysisResponse(
                    symbol=str(val.get("symbol", "")),
                    scanned_at=row.time.isoformat(),
                    composite_score=float(val.get("composite_score", 0.0)),
                    category_scores=CategoryScores(**val.get("category_scores", {})),
                    profile_matches=val.get("profile_matches", []),
                    signals=val.get("signals", {}),
                    meta=AnalysisMeta(
                        atr=float(meta_raw.get("atr", 0.0)),
                        atr_pct=float(meta_raw.get("atr_pct", 0.0)),
                        last_price=float(meta_raw.get("last_price", 0.0)),
                        volume_ratio=float(meta_raw.get("volume_ratio", 0.0)),
                        price_change_pct=float(meta_raw.get("price_change_pct", 0.0)),
                        timestamp=str(meta_raw.get("timestamp", "")),
                        bars=int(meta_raw.get("bars", 0)),
                    ),
                    harmonics=_dict_to_harmonic_info(val.get("harmonics")),
                    is_actionable=bool(val.get("is_actionable", False)),
                    volume_contradiction=bool(val.get("volume_contradiction", False)),
                )
            )
        except Exception as exc:
            log.warning("Failed to parse cached result: %s", exc)

    # Sort by composite score descending
    responses.sort(key=lambda r: r.composite_score, reverse=True)

    # Filter by profile if requested
    if profile:
        canonical = _normalize_profile_name(profile)
        responses = [r for r in responses if canonical in r.profile_matches]

    # Assign rank (1 = highest composite score)
    for i, resp in enumerate(responses):
        resp.rank = i + 1

    return responses


@router.get("/results/{symbol}", response_model=AnalysisResponse)
async def get_symbol_result(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="Timeframe: 1d or 1w")] = "1d",
) -> AnalysisResponse:
    """Return full analysis detail for a single ticker."""
    tf_enum = _TF_MAP.get(timeframe, TimeframeEnum.D1)

    # Resolve symbol_id
    sym_result = await session.execute(
        select(Symbol.id).where(Symbol.ticker == symbol.upper())
    )
    symbol_id = sym_result.scalar_one_or_none()
    if symbol_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Symbol {symbol} not found")

    cache_result = await session.execute(
        select(IndicatorCache)
        .where(
            IndicatorCache.symbol_id == symbol_id,
            IndicatorCache.indicator_name == "full_analysis",
            IndicatorCache.timeframe == tf_enum,
        )
        .order_by(desc(IndicatorCache.time))
        .limit(1)
    )
    row = cache_result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No cached {timeframe} analysis for {symbol}. Run /scanner/run/{symbol} first.",
        )

    val = row.value
    meta_raw = val.get("meta", {})
    return AnalysisResponse(
        symbol=str(val.get("symbol", "")),
        scanned_at=row.time.isoformat(),
        composite_score=float(val.get("composite_score", 0.0)),
        category_scores=CategoryScores(**val.get("category_scores", {})),
        profile_matches=val.get("profile_matches", []),
        signals=val.get("signals", {}),
        meta=AnalysisMeta(
            atr=float(meta_raw.get("atr", 0.0)),
            atr_pct=float(meta_raw.get("atr_pct", 0.0)),
            last_price=float(meta_raw.get("last_price", 0.0)),
            volume_ratio=float(meta_raw.get("volume_ratio", 0.0)),
            price_change_pct=float(meta_raw.get("price_change_pct", 0.0)),
            timestamp=str(meta_raw.get("timestamp", "")),
            bars=int(meta_raw.get("bars", 0)),
        ),
        harmonics=_dict_to_harmonic_info(val.get("harmonics")),
        is_actionable=bool(val.get("is_actionable", False)),
        volume_contradiction=bool(val.get("volume_contradiction", False)),
    )


@router.get("/profiles", response_model=list[ProfileInfo])
async def list_profiles() -> list[ProfileInfo]:
    """List all scanner profiles with their configurations."""
    return [
        ProfileInfo(
            name=p.name,
            description=p.description,
            score_threshold=p.score_threshold,
            required_conditions=p.required_conditions,
        )
        for p in PROFILES.values()
    ]


@router.post("/run/{symbol}", response_model=AnalysisResponse)
async def run_symbol_analysis(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="Timeframe: 1d or 1w")] = "1d",
) -> AnalysisResponse:
    """Run on-demand analysis for a single ticker (inline, returns immediately)."""
    tf_enum = _TF_MAP.get(timeframe, TimeframeEnum.D1)

    sym_result = await session.execute(
        select(Symbol).where(Symbol.ticker == symbol.upper())
    )
    sym = sym_result.scalar_one_or_none()
    if sym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Symbol {symbol} not found")

    result = await run_analysis_for_ticker(sym.id, sym.ticker, session, timeframe=tf_enum)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient {timeframe} OHLCV data for {symbol}. Trigger a data refresh first.",
        )

    await session.commit()
    return _result_to_response(result)
