"""
On-demand intraday OHLCV fetcher.

The OHLCV router stores daily and hourly bars in the TimescaleDB hypertable
via the nightly ingestion job, but sub-daily bars (1/5/15/30 minute) are not
persisted yet — that fetcher is a follow-on task. For now, the API serves
intraday timeframes by calling yfinance directly on demand.

yfinance availability windows (rolling, from `now`):
    1m   →  7 calendar days
    5m   → 60 calendar days
    15m  → 60 calendar days
    30m  → 60 calendar days

The synchronous yfinance call is offloaded to the default thread pool via
`loop.run_in_executor`, consistent with `app/ingestion/fetcher.py`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


# Public API timeframe string → yfinance interval string.
INTRADAY_INTERVALS: Final[dict[str, str]] = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
}

# Maximum trailing window yfinance will serve, by API timeframe.
INTRADAY_MAX_DAYS: Final[dict[str, int]] = {
    "1min": 7,
    "5min": 60,
    "15min": 60,
    "30min": 60,
}

# Approximate trading bars per regular session (6.5h × 60m / interval).
_BARS_PER_TRADING_DAY: Final[dict[str, int]] = {
    "1min": 390,
    "5min": 78,
    "15min": 26,
    "30min": 13,
}


class IntradayUnavailableError(Exception):
    """Raised when an intraday request exceeds the yfinance availability window."""


def is_intraday_timeframe(timeframe: str) -> bool:
    """True if `timeframe` is one of the on-demand intraday strings."""
    return timeframe in INTRADAY_INTERVALS


def max_bars_for_timeframe(timeframe: str) -> int:
    """Approximate maximum bars yfinance will return for `timeframe`."""
    if timeframe not in INTRADAY_INTERVALS:
        raise ValueError(f"Not an intraday timeframe: {timeframe!r}")
    return INTRADAY_MAX_DAYS[timeframe] * _BARS_PER_TRADING_DAY[timeframe]


def _fetch_sync(symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
    """
    Synchronous yfinance fetch — must be called from a thread pool.

    Returns a DataFrame with columns: time (UTC tz-aware), open, high, low,
    close, volume. Empty DataFrame if yfinance returned no rows.
    """
    interval = INTRADAY_INTERVALS[timeframe]
    period = f"{INTRADAY_MAX_DAYS[timeframe]}d"

    try:
        ticker = yf.Ticker(symbol.upper())
        history = ticker.history(period=period, interval=interval, auto_adjust=False)
    except Exception as exc:  # noqa: BLE001 — yfinance raises a variety of types
        logger.warning("yfinance intraday fetch failed for %s/%s: %s", symbol, interval, exc)
        raise

    if history is None or history.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    history = history.tail(bars)

    # yfinance returns a DatetimeIndex; ensure UTC tz so downstream
    # `pd.Timestamp(t).timestamp()` produces correct epoch seconds.
    if history.index.tz is None:
        index_utc = history.index.tz_localize("UTC")
    else:
        index_utc = history.index.tz_convert("UTC")

    return pd.DataFrame(
        {
            "time": index_utc,
            "open": history["Open"].astype(float).to_numpy(),
            "high": history["High"].astype(float).to_numpy(),
            "low": history["Low"].astype(float).to_numpy(),
            "close": history["Close"].astype(float).to_numpy(),
            "volume": history["Volume"].astype("int64").to_numpy(),
        }
    ).reset_index(drop=True)


async def fetch_intraday_ohlcv(symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
    """
    Fetch on-demand intraday OHLCV bars for `symbol` at `timeframe`.

    Args:
        symbol: Ticker symbol (case-insensitive).
        timeframe: One of "1min", "5min", "15min", "30min".
        bars: Number of bars requested. Must be ≤ the yfinance window cap
            for the timeframe (see `max_bars_for_timeframe`).

    Raises:
        ValueError: when `timeframe` is not an intraday timeframe.
        IntradayUnavailableError: when `bars` exceeds yfinance's rolling
            availability window for `timeframe`.
    """
    if not is_intraday_timeframe(timeframe):
        raise ValueError(f"Not an intraday timeframe: {timeframe!r}")

    cap = max_bars_for_timeframe(timeframe)
    if bars > cap:
        raise IntradayUnavailableError(
            f"yfinance only provides ~{cap} {timeframe} bars "
            f"(rolling {INTRADAY_MAX_DAYS[timeframe]}-day window). "
            f"Requested {bars}."
        )

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_sync, symbol, timeframe, bars)
