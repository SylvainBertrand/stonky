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
        pg_insert(OHLCV.__table__)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["time", "symbol_id", "timeframe"])
    )
    result = await session.execute(stmt)
    # rowcount = rows actually inserted (0 for conflicts)
    return result.rowcount if result.rowcount >= 0 else len(rows)


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
