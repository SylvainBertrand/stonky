"""
Analysis pipeline: orchestrates indicator computation, scoring, and profile matching.

Pure sync analysis function + async DB-integrated wrappers.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pandas_ta as ta
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.indicators.divergence import (
    compute_macd_divergence_signals,
    compute_rsi_divergence_signals,
)
from app.analysis.indicators.momentum import (
    compute_macd_signals,
    compute_rsi_signals,
    compute_stoch_signals,
)
from app.analysis.indicators.patterns import compute_candlestick_signals
from app.analysis.indicators.support_resistance import (
    compute_fibonacci_signals,
    compute_pivot_signals,
)
from app.analysis.indicators.trend import (
    compute_adx_signals,
    compute_ema_signals,
    compute_supertrend_signals,
)
from app.analysis.indicators.volatility import (
    compute_atr_signals,
    compute_bbands_signals,
    compute_ttm_squeeze_signals,
)
from app.analysis.indicators.volume import (
    compute_cmf_signals,
    compute_obv_signals,
    compute_vwap_signals,
)
from app.analysis.profiles import evaluate_profiles
from app.analysis.scoring import build_composite
from app.models.enums import TimeframeEnum
from app.models.indicator_cache import IndicatorCache
from app.models.ohlcv import OHLCV

log = logging.getLogger(__name__)

MIN_BARS = 200
_INDICATOR_NAME = "full_analysis"


@dataclass
class AnalysisResult:
    symbol: str
    composite_score: float
    category_scores: dict[str, float]
    profile_matches: list[str]
    signals: dict[str, float]
    meta: dict[str, Any]


def _safe_signals(fn: Any, df: pd.DataFrame, key: str) -> dict[str, float]:
    """Call indicator signal function, return {key: 0.0} on any failure."""
    try:
        result = fn(df)
        return result if result else {key: 0.0}
    except Exception as exc:
        log.debug("Indicator %s failed: %s", fn.__name__, exc)
        return {key: 0.0}


def run_analysis(df: pd.DataFrame, symbol: str) -> AnalysisResult:
    """
    Pure sync pipeline. Runs full TA computation on an OHLCV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with columns: open, high, low, close, volume.
    symbol : str
        Ticker symbol (for labeling only).

    Returns
    -------
    AnalysisResult
    """
    if len(df) < MIN_BARS:
        log.warning("%s: insufficient bars (%d < %d)", symbol, len(df), MIN_BARS)

    # Compute ATR for meta
    atr_val = 0.0
    last_price = float(df["close"].iloc[-1]) if not df.empty else 0.0
    try:
        atr_series = ta.atr(df["high"], df["low"], df["close"], length=14)
        if atr_series is not None:
            clean = atr_series.dropna()
            if not clean.empty:
                atr_val = float(clean.iloc[-1])
    except Exception:
        pass

    atr_pct = (atr_val / last_price * 100.0) if last_price > 0 else 0.0

    # Collect all signals — wrap each in try/except
    all_signals: dict[str, float] = {}

    for fn in (compute_ema_signals, compute_adx_signals, compute_supertrend_signals):
        all_signals.update(_safe_signals(fn, df, fn.__name__))

    for fn in (compute_rsi_signals, compute_macd_signals, compute_stoch_signals):
        all_signals.update(_safe_signals(fn, df, fn.__name__))

    for fn in (compute_bbands_signals, compute_atr_signals, compute_ttm_squeeze_signals):
        all_signals.update(_safe_signals(fn, df, fn.__name__))

    for fn in (compute_obv_signals, compute_vwap_signals, compute_cmf_signals):
        all_signals.update(_safe_signals(fn, df, fn.__name__))

    for fn in (compute_fibonacci_signals, compute_pivot_signals):
        all_signals.update(_safe_signals(fn, df, fn.__name__))

    for fn in (compute_rsi_divergence_signals, compute_macd_divergence_signals):
        all_signals.update(_safe_signals(fn, df, fn.__name__))

    all_signals.update(_safe_signals(compute_candlestick_signals, df, "compute_candlestick_signals"))

    category_scores, comp = build_composite(all_signals)
    profile_matches = evaluate_profiles(all_signals, category_scores, comp)

    timestamp = df["time"].iloc[-1] if "time" in df.columns else datetime.now(timezone.utc)
    if hasattr(timestamp, "to_pydatetime"):
        timestamp = timestamp.to_pydatetime()

    return AnalysisResult(
        symbol=symbol,
        composite_score=round(comp, 6),
        category_scores={k: round(v, 6) for k, v in category_scores.items()},
        profile_matches=profile_matches,
        signals={k: round(v, 6) for k, v in all_signals.items()},
        meta={
            "atr": round(atr_val, 6),
            "atr_pct": round(atr_pct, 4),
            "last_price": round(last_price, 4),
            "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
            "bars": len(df),
        },
    )


async def fetch_ohlcv_for_symbol(
    symbol_id: int,
    ticker: str,
    db: AsyncSession,
    timeframe: TimeframeEnum = TimeframeEnum.D1,
    limit: int = 500,
) -> pd.DataFrame | None:
    """Fetch OHLCV from DB, return DataFrame or None if insufficient data."""
    try:
        result = await db.execute(
            select(OHLCV)
            .where(OHLCV.symbol_id == symbol_id, OHLCV.timeframe == timeframe)
            .order_by(desc(OHLCV.time))
            .limit(limit)
        )
        rows = result.scalars().all()
        if not rows or len(rows) < 20:
            log.debug("%s: not enough OHLCV rows (%d)", ticker, len(rows) if rows else 0)
            return None

        data = [
            {
                "time": row.time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": int(row.volume),
            }
            for row in reversed(rows)  # ascending time order
        ]
        return pd.DataFrame(data)
    except Exception as exc:
        log.error("Failed to fetch OHLCV for %s: %s", ticker, exc)
        return None


def _params_hash(timeframe: TimeframeEnum) -> str:
    return hashlib.md5(timeframe.value.encode()).hexdigest()


async def run_analysis_for_ticker(
    symbol_id: int,
    ticker: str,
    db: AsyncSession,
    timeframe: TimeframeEnum = TimeframeEnum.D1,
) -> AnalysisResult | None:
    """Async: fetch OHLCV from DB, run sync analysis, cache result in indicator_cache."""
    df = await fetch_ohlcv_for_symbol(symbol_id, ticker, db, timeframe)
    if df is None:
        return None

    # Run sync analysis in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_analysis, df, ticker)

    # Cache in indicator_cache
    try:
        now = datetime.now(timezone.utc)
        params_hash = _params_hash(timeframe)
        cache_value: dict[str, Any] = {
            "symbol": result.symbol,
            "composite_score": result.composite_score,
            "category_scores": result.category_scores,
            "profile_matches": result.profile_matches,
            "signals": result.signals,
            "meta": result.meta,
        }

        # Upsert: delete existing then insert
        existing = await db.execute(
            select(IndicatorCache).where(
                IndicatorCache.symbol_id == symbol_id,
                IndicatorCache.timeframe == timeframe,
                IndicatorCache.indicator_name == _INDICATOR_NAME,
                IndicatorCache.params_hash == params_hash,
            )
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row is not None:
            existing_row.value = cache_value
            existing_row.time = now
        else:
            db.add(
                IndicatorCache(
                    time=now,
                    symbol_id=symbol_id,
                    timeframe=timeframe,
                    indicator_name=_INDICATOR_NAME,
                    params_hash=params_hash,
                    value=cache_value,
                )
            )
        await db.flush()
    except Exception as exc:
        log.warning("Failed to cache analysis for %s: %s", ticker, exc)

    return result


async def run_scanner(
    symbol_ids: list[tuple[int, str]],
    db: AsyncSession,
    timeframe: TimeframeEnum = TimeframeEnum.D1,
    concurrency: int = 10,
) -> list[AnalysisResult]:
    """
    Run analysis for all symbols concurrently (semaphore-limited).
    Returns results sorted by composite_score descending.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _run_one(symbol_id: int, ticker: str) -> AnalysisResult | None:
        async with sem:
            return await run_analysis_for_ticker(symbol_id, ticker, db, timeframe)

    tasks = [_run_one(sid, ticker) for sid, ticker in symbol_ids]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[AnalysisResult] = []
    for item in raw:
        if isinstance(item, AnalysisResult):
            results.append(item)
        elif isinstance(item, Exception):
            log.error("Scanner task failed: %s", item)

    results.sort(key=lambda r: r.composite_score, reverse=True)
    return results
