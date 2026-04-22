"""yfinance OHLCV fetcher.

Supports:
- Backfill mode: fetch N years/months of history per timeframe default
- Incremental mode: fetch only bars since the last stored bar (1-day overlap)
- Async-safe: yfinance is blocking, wrapped in run_in_executor
- OHLCV upsert: ON CONFLICT DO NOTHING (idempotent)
- Ingestion log: records each fetch attempt with status/error
"""

from __future__ import annotations

import asyncio
import functools
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TimeframeEnum
from app.models.ingestion_log import IngestionLog
from app.models.ohlcv import OHLCV
from app.models.symbols import Symbol

logger = logging.getLogger(__name__)

# yfinance interval strings per timeframe
_YF_INTERVAL: dict[TimeframeEnum, str] = {
    TimeframeEnum.M1: "1m",
    TimeframeEnum.M5: "5m",
    TimeframeEnum.M15: "15m",
    TimeframeEnum.M30: "30m",
    TimeframeEnum.H1: "1h",
    TimeframeEnum.H4: "4h",  # yfinance doesn't support 4h natively; maps to 1h
    TimeframeEnum.D1: "1d",
    TimeframeEnum.W1: "1wk",
    TimeframeEnum.MO1: "1mo",
}

# Default backfill periods when no incremental start exists
_BACKFILL_PERIOD: dict[TimeframeEnum, str] = {
    TimeframeEnum.M1: "7d",
    TimeframeEnum.M5: "60d",
    TimeframeEnum.M15: "60d",
    TimeframeEnum.M30: "60d",
    TimeframeEnum.H1: "730d",
    TimeframeEnum.H4: "730d",
    TimeframeEnum.D1: "5y",
    TimeframeEnum.W1: "10y",
    TimeframeEnum.MO1: "max",
}


def _fetch_yfinance_sync(
    ticker: str,
    interval: str,
    period: str | None,
    start: str | None,
) -> pd.DataFrame:
    """Blocking yfinance call — always run via run_in_executor."""
    t = yf.Ticker(ticker)
    if start:
        return t.history(interval=interval, start=start, auto_adjust=True)
    return t.history(interval=interval, period=period or "5y", auto_adjust=True)


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a raw yfinance DataFrame into the canonical schema."""
    if df.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "adj_close"])

    df = df.reset_index()
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]

    # Rename DatetimeIndex column (daily → "date", intraday → "datetime")
    if "date" in df.columns:
        df = df.rename(columns={"date": "time"})
    elif "datetime" in df.columns:
        df = df.rename(columns={"datetime": "time"})

    # Ensure tz-aware UTC
    if df["time"].dt.tz is None:
        df["time"] = df["time"].dt.tz_localize("UTC")
    else:
        df["time"] = df["time"].dt.tz_convert("UTC")

    # Keep only the columns we store; adj_close mirrors close (already adjusted)
    keep = ["time", "open", "high", "low", "close", "volume"]
    available = [c for c in keep if c in df.columns]
    df = df[available].copy()
    df["adj_close"] = df["close"]

    return df


async def fetch_ohlcv(
    ticker: str,
    timeframe: TimeframeEnum = TimeframeEnum.D1,
    period: str | None = None,
    start: str | None = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV bars for *ticker* via yfinance (async-safe).

    Returns a normalized DataFrame with columns:
    time (UTC datetime), open, high, low, close, volume, adj_close.
    """
    interval = _YF_INTERVAL[timeframe]
    loop = asyncio.get_event_loop()
    fn = functools.partial(_fetch_yfinance_sync, ticker, interval, period, start)
    raw = await loop.run_in_executor(None, fn)
    return _normalize_df(raw)


async def store_ohlcv(
    session: AsyncSession,
    symbol_id: int,
    df: pd.DataFrame,
    timeframe: TimeframeEnum,
) -> int:
    """
    Bulk-upsert OHLCV rows using ON CONFLICT DO NOTHING.

    Passes timeframe as its string value so the Core insert bypasses
    ORM enum processing and matches the PostgreSQL enum directly.

    Returns the number of rows inserted (0 for already-existing rows).
    """
    if df.empty:
        return 0

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        t = row["time"]
        if hasattr(t, "to_pydatetime"):
            t = t.to_pydatetime()
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)

        rows.append(
            {
                "time": t,
                "symbol_id": symbol_id,
                "timeframe": timeframe.value,  # string "1d", not enum name
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row.get("volume", 0)),
                "adj_close": float(row.get("adj_close", row["close"])),
            }
        )

    stmt = (
        pg_insert(OHLCV)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["time", "symbol_id", "timeframe"])
    )
    result = await session.execute(stmt)
    # rowcount = rows actually inserted (0 for conflicts)
    return result.rowcount if result.rowcount >= 0 else len(rows)  # type: ignore[attr-defined]  # CursorResult for DML has rowcount; stubs expose Result[Any]


async def _latest_bar(
    session: AsyncSession, symbol_id: int, timeframe: TimeframeEnum
) -> datetime | None:
    """Return the timestamp of the most recent stored bar, or None."""
    result = await session.execute(
        select(OHLCV.time)
        .where(OHLCV.symbol_id == symbol_id, OHLCV.timeframe == timeframe)
        .order_by(OHLCV.time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def ensure_symbols(
    session: AsyncSession,
    tickers: list[str],
) -> dict[str, int]:
    """Bulk-create Symbol records for unknown tickers (concurrency-safe).

    Uses INSERT ... ON CONFLICT DO NOTHING to handle concurrent calls.
    Returns a mapping of uppercase ticker → symbol_id for ALL requested tickers
    (both pre-existing and newly created).
    """
    upper_tickers = list({t.upper() for t in tickers})
    if not upper_tickers:
        return {}

    # Find existing symbols
    existing = (
        await session.execute(
            select(Symbol.ticker, Symbol.id).where(Symbol.ticker.in_(upper_tickers))
        )
    ).all()
    existing_map = {row[0]: row[1] for row in existing}

    missing = [t for t in upper_tickers if t not in existing_map]
    if missing:
        stmt = (
            pg_insert(Symbol)
            .values([{"ticker": t, "asset_type": "stock"} for t in missing])
            .on_conflict_do_nothing(index_elements=["ticker"])
        )
        await session.execute(stmt)
        await session.flush()

        # Re-query to pick up IDs (includes rows created by concurrent callers)
        new_rows = (
            await session.execute(
                select(Symbol.ticker, Symbol.id).where(Symbol.ticker.in_(missing))
            )
        ).all()
        for row in new_rows:
            existing_map[row[0]] = row[1]

        logger.info("ensure_symbols: created %d new symbol(s)", len(missing))

    return existing_map


def _batch_download_sync(
    tickers: list[str],
    period: str,
    interval: str,
) -> dict[str, pd.DataFrame]:
    """Blocking batch download via yf.download — run via run_in_executor.

    Returns a dict of ticker → normalized DataFrame.
    """
    if not tickers:
        return {}

    raw = yf.download(
        tickers,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )

    result: dict[str, pd.DataFrame] = {}

    if len(tickers) == 1:
        # yf.download returns a simple DataFrame for a single ticker
        ticker = tickers[0]
        df = _normalize_df(raw)
        if not df.empty:
            result[ticker] = df
    else:
        # Multi-ticker: columns are MultiIndex (ticker, field)
        for ticker in tickers:
            try:
                ticker_df = raw[ticker].dropna(how="all")
                df = _normalize_df(ticker_df)
                if not df.empty:
                    result[ticker] = df
            except (KeyError, TypeError):
                logger.warning("batch_download: no data for %s", ticker)

    return result


async def batch_backfill_ohlcv(
    session: AsyncSession,
    symbol_map: dict[str, int],
    timeframe: TimeframeEnum = TimeframeEnum.D1,
    period: str = "1y",
) -> dict[str, Any]:
    """Batch-fetch OHLCV for symbols that have no stored data.

    Uses yf.download for efficient multi-ticker download.
    Only fetches for symbols with zero existing bars (first-time hydration).

    Returns {hydrated: int, failed: int, skipped: int}.
    """
    if not symbol_map:
        return {"hydrated": 0, "failed": 0, "skipped": 0}

    # Find which symbols already have OHLCV data
    needs_hydration: list[str] = []
    for ticker, symbol_id in symbol_map.items():
        latest = await _latest_bar(session, symbol_id, timeframe)
        if latest is None:
            needs_hydration.append(ticker)

    if not needs_hydration:
        return {"hydrated": 0, "failed": 0, "skipped": len(symbol_map)}

    logger.info(
        "batch_backfill_ohlcv: hydrating %d/%d tickers (period=%s)",
        len(needs_hydration),
        len(symbol_map),
        period,
    )

    # Batch download (runs in executor to avoid blocking the event loop)
    interval = _YF_INTERVAL[timeframe]
    loop = asyncio.get_event_loop()
    fn = functools.partial(_batch_download_sync, needs_hydration, period, interval)
    downloaded = await loop.run_in_executor(None, fn)

    # Store results
    hydrated = 0
    failed = 0
    for ticker in needs_hydration:
        symbol_id = symbol_map[ticker]
        df = downloaded.get(ticker)
        if df is None or df.empty:
            failed += 1
            logger.warning("batch_backfill_ohlcv: no data for %s", ticker)
            continue

        try:
            bars = await store_ohlcv(session, symbol_id, df, timeframe)
            hydrated += 1
            logger.info("batch_backfill_ohlcv: stored %d bars for %s", bars, ticker)
        except Exception as exc:
            failed += 1
            logger.error("batch_backfill_ohlcv: store failed for %s: %s", ticker, exc)

    return {
        "hydrated": hydrated,
        "failed": failed,
        "skipped": len(symbol_map) - len(needs_hydration),
    }


async def fetch_and_store(
    session: AsyncSession,
    tickers: list[str],
    timeframe: TimeframeEnum = TimeframeEnum.D1,
    incremental: bool = True,
    period: str | None = None,
) -> dict[str, Any]:
    """
    Fetch and store OHLCV bars for a list of tickers.

    Args:
        session:     Async DB session; caller must commit/rollback.
        tickers:     List of ticker symbols to refresh.
        timeframe:   Timeframe to fetch.
        incremental: If True, only fetch bars since the last stored bar.
        period:      yfinance period string for full backfill (e.g. "5y").
                     Ignored in incremental mode when a latest bar exists.

    Returns:
        {fetched, failed, tickers_ok, tickers_failed}
    """
    results: dict[str, Any] = {
        "fetched": 0,
        "failed": 0,
        "tickers_ok": [],
        "tickers_failed": [],
    }

    for ticker in tickers:
        upper = ticker.upper()

        # Resolve symbol_id
        sym_row = await session.execute(
            select(Symbol.id).where(Symbol.ticker == upper, Symbol.is_active.is_(True))
        )
        symbol_id: int | None = sym_row.scalar_one_or_none()

        if symbol_id is None:
            logger.warning("Ticker %s not in symbols table — skipping", upper)
            results["failed"] += 1
            results["tickers_failed"].append(upper)
            continue

        # Determine fetch parameters
        start: str | None = None
        backfill_period = period or _BACKFILL_PERIOD[timeframe]

        if incremental:
            latest = await _latest_bar(session, symbol_id, timeframe)
            if latest is not None:
                # 1-day overlap to handle partial/delayed bars
                start = (latest - timedelta(days=1)).strftime("%Y-%m-%d")

        fetch_start = datetime.now(UTC)
        try:
            df = await fetch_ohlcv(
                upper,
                timeframe,
                period=None if start else backfill_period,
                start=start,
            )
            bars = await store_ohlcv(session, symbol_id, df, timeframe)

            latest_bar: datetime | None = None
            if not df.empty:
                ts = df["time"].max()
                latest_bar = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                if latest_bar.tzinfo is None:
                    latest_bar = latest_bar.replace(tzinfo=UTC)

            session.add(
                IngestionLog(
                    symbol_id=symbol_id,
                    timeframe=timeframe,
                    source="yfinance",
                    bars_fetched=bars,
                    latest_bar=latest_bar,
                    status="success",
                    fetched_at=fetch_start,
                )
            )
            results["fetched"] += bars
            results["tickers_ok"].append(upper)
            logger.info("Stored %d bars for %s (%s)", bars, upper, timeframe.value)

        except Exception as exc:
            logger.exception("Failed to fetch %s", upper)
            session.add(
                IngestionLog(
                    symbol_id=symbol_id,
                    timeframe=timeframe,
                    source="yfinance",
                    bars_fetched=0,
                    status="error",
                    error_message=str(exc)[:500],
                    fetched_at=fetch_start,
                )
            )
            results["failed"] += 1
            results["tickers_failed"].append(upper)

    return results
