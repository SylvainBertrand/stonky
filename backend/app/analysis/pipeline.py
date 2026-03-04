"""
Analysis pipeline: orchestrates indicator computation, scoring, and profile matching.

Pure sync analysis function + async DB-integrated wrappers.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
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
from app.analysis.indicators.harmonics import (
    HarmonicMatch,
    compute_harmonics_signals,
    detect_harmonics,
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
from app.db.session import AsyncSessionLocal
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
    harmonics: dict[str, Any] | None = None
    is_actionable: bool = False
    volume_contradiction: bool = False


def _passes_confluence(category_scores: dict[str, float], composite: float) -> bool:
    """
    Return True if ≥3 of 7 categories agree with composite direction (|score| > 0.1).
    A near-zero composite (|comp| < 0.05) is not actionable.
    """
    if abs(composite) < 0.05:
        return False
    threshold = 0.1
    if composite > 0:
        agreeing = sum(1 for s in category_scores.values() if s > threshold)
    else:
        agreeing = sum(1 for s in category_scores.values() if s < -threshold)
    return agreeing >= 3


def _has_volume_contradiction(signals: dict[str, float], composite: float) -> bool:
    """
    True when OBV and CMF both contradict the composite direction.
    Flags: composite bullish but obv<0 and cmf<0, or vice versa.
    """
    obv = signals.get("obv", 0.0)
    cmf = signals.get("cmf", 0.0)
    if composite > 0.1 and obv < 0 and cmf < 0:
        return True
    if composite < -0.1 and obv > 0 and cmf > 0:
        return True
    return False


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

    # Compute ATR and volume ratio for meta
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

    volume_ratio = 0.0
    try:
        vol = df["volume"].astype(float)
        avg_vol = vol.rolling(20).mean().iloc[-1]
        if avg_vol > 0:
            volume_ratio = float(vol.iloc[-1]) / float(avg_vol)
    except Exception:
        pass

    price_change_pct = 0.0
    try:
        if len(df) >= 2:
            prev_close = float(df["close"].iloc[-2])
            if prev_close > 0:
                price_change_pct = round((last_price - prev_close) / prev_close * 100.0, 4)
    except Exception:
        pass

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

    # Harmonic detection — CPU-intensive; wrapped in try/except inside detect_harmonics
    harmonic_matches: list[HarmonicMatch] = []
    harmonic_detail: dict[str, Any] | None = None
    try:
        harmonic_matches = detect_harmonics(df)
        harmonic_float_signals = compute_harmonics_signals(df, harmonic_matches)
        all_signals.update(harmonic_float_signals)

        if harmonic_matches:
            best = harmonic_matches[0]
            harmonic_detail = {
                "detected": True,
                "pattern": best.pattern_name,
                "direction": best.direction,
                "ratio_quality": round(best.ratio_quality, 4),
                "in_prz": harmonic_float_signals.get("harmonic_in_prz", 0.0) > 0.5,
                "prz_low": round(best.prz_low, 4),
                "prz_high": round(best.prz_high, 4),
                "bars_since_completion": best.bars_since_completion,
            }
    except Exception as exc:
        log.warning("Harmonic analysis failed for %s: %s", symbol, exc)

    category_scores, comp = build_composite(all_signals)
    profile_matches = evaluate_profiles(all_signals, category_scores, comp)

    log.info(
        "Analysis %s: bars=%d, composite=%.4f, profiles=%s, actionable=%s",
        symbol,
        len(df),
        comp,
        profile_matches,
        _passes_confluence(category_scores, comp),
    )

    is_actionable = _passes_confluence(category_scores, comp)
    vol_contradiction = _has_volume_contradiction(all_signals, comp)

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
            "volume_ratio": round(volume_ratio, 4),
            "price_change_pct": price_change_pct,
            "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
            "bars": len(df),
        },
        harmonics=harmonic_detail,
        is_actionable=is_actionable,
        volume_contradiction=vol_contradiction,
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
        if data:
            log.info(
                "%s: fetched %d %s bars (%s → %s)",
                ticker,
                len(data),
                timeframe.value,
                data[0]["time"],
                data[-1]["time"],
            )
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
            "harmonics": result.harmonics,
            "is_actionable": result.is_actionable,
            "volume_contradiction": result.volume_contradiction,
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
            cache_action = "updated"
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
            cache_action = "inserted"
        await db.flush()
        log.info(
            "%s: cache %s for %s (%s), composite=%.4f, profile_matches=%s",
            ticker,
            cache_action,
            _INDICATOR_NAME,
            timeframe.value,
            result.composite_score,
            result.profile_matches,
        )
    except Exception as exc:
        log.warning("Failed to cache analysis for %s: %s", ticker, exc)

    return result


async def run_scanner(
    symbol_ids: list[tuple[int, str]],
    timeframe: TimeframeEnum = TimeframeEnum.D1,
    concurrency: int = 10,
) -> list[AnalysisResult]:
    """
    Run analysis for all symbols concurrently (semaphore-limited).
    Each symbol gets its own DB session to avoid concurrent-flush conflicts.
    Returns results sorted by composite_score descending.
    """
    sem = asyncio.Semaphore(concurrency)

    log.info(
        "Scanner start: timeframe=%s, symbols=%d, concurrency=%d",
        timeframe.value,
        len(symbol_ids),
        concurrency,
    )

    async def _run_one(symbol_id: int, ticker: str) -> AnalysisResult | None:
        async with sem:
            async with AsyncSessionLocal() as db:
                log.info("Scanner symbol start: %s (id=%d)", ticker, symbol_id)
                result = await run_analysis_for_ticker(symbol_id, ticker, db, timeframe)
                await db.commit()
                if result is None:
                    log.info("Scanner symbol skipped: %s (id=%d) - no analyzable OHLCV", ticker, symbol_id)
                else:
                    log.info(
                        "Scanner symbol done: %s (id=%d), score=%.4f, profiles=%s",
                        ticker,
                        symbol_id,
                        result.composite_score,
                        result.profile_matches,
                    )
                return result

    tasks = [_run_one(sid, ticker) for sid, ticker in symbol_ids]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[AnalysisResult] = []
    for item in raw:
        if isinstance(item, AnalysisResult):
            results.append(item)
        elif isinstance(item, Exception):
            log.error("Scanner task failed: %s", item)

    results.sort(key=lambda r: r.composite_score, reverse=True)
    log.info(
        "Scanner end: analyzed=%d, top=%s",
        len(results),
        [
            {
                "symbol": r.symbol,
                "score": round(r.composite_score, 4),
                "profiles": r.profile_matches,
            }
            for r in results[:5]
        ],
    )
    return results
