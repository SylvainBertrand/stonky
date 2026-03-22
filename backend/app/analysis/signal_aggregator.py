"""Signal aggregator — collects all available signals for a symbol into a single structure.

This is a pure data-collection layer (no LLM). The resulting AggregatedSignals
is serialized into the LLM prompt and also stored for debugging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TimeframeEnum
from app.models.forecast_cache import ForecastCache
from app.models.indicator_cache import IndicatorCache
from app.models.pattern_detections import PatternDetection
from app.models.symbols import Symbol

log = logging.getLogger(__name__)

_INDICATOR_NAME = "full_analysis"


@dataclass
class AggregatedSignals:
    symbol: str
    timeframe: str
    as_of_date: str

    # P0 scoring
    composite_score: float
    category_scores: dict[str, float] = field(default_factory=dict)
    active_profile_matches: list[str] = field(default_factory=list)

    # P0 key indicators
    indicators: dict[str, float] = field(default_factory=dict)

    # P0 support/resistance
    entry_zone: float | None = None
    stop_level: float | None = None
    target_level: float | None = None
    risk_reward_ratio: float | None = None

    # P1 chart patterns (YOLOv8)
    chart_patterns: list[dict[str, Any]] = field(default_factory=list)

    # P1 Elliott Wave
    ew_summary: str | None = None
    ew_invalidation: float | None = None

    # P1 Chronos-2 forecast
    forecast_direction: str | None = None
    forecast_expected_move_pct: float | None = None
    forecast_confidence: float | None = None
    forecast_range_low: float | None = None
    forecast_range_high: float | None = None

    # Price context
    last_close: float = 0.0
    price_vs_ema21: float = 0.0
    price_vs_ema200: float = 0.0
    atr_pct: float = 0.0


async def aggregate_signals(
    symbol: str,
    db: AsyncSession,
    timeframe: str = "D1",
) -> AggregatedSignals | None:
    """Pull latest data for symbol from indicator_cache, pattern_detections, forecast_cache.

    Returns None if no P0 scan results exist (insufficient data).
    """
    # Resolve symbol_id
    sym_result = await db.execute(select(Symbol.id).where(Symbol.ticker == symbol.upper()))
    symbol_id = sym_result.scalar_one_or_none()
    if symbol_id is None:
        return None

    # Pull latest cached analysis from indicator_cache
    tf_enum = TimeframeEnum.D1 if timeframe == "D1" else TimeframeEnum.W1
    cache_result = await db.execute(
        select(IndicatorCache.value, IndicatorCache.time)
        .where(
            IndicatorCache.symbol_id == symbol_id,
            IndicatorCache.timeframe == tf_enum,
            IndicatorCache.indicator_name == _INDICATOR_NAME,
        )
        .order_by(desc(IndicatorCache.time))
        .limit(1)
    )
    cache_row = cache_result.first()
    if cache_row is None:
        return None

    cached_value: dict[str, Any] = cache_row[0]
    cache_time = cache_row[1]

    signals: dict[str, float] = cached_value.get("signals", {})
    category_scores: dict[str, float] = cached_value.get("category_scores", {})
    meta: dict[str, Any] = cached_value.get("meta", {})

    agg = AggregatedSignals(
        symbol=symbol.upper(),
        timeframe=timeframe,
        as_of_date=cache_time.strftime("%Y-%m-%d") if cache_time else "",
        composite_score=float(cached_value.get("composite_score", 0.0)),
        category_scores=category_scores,
        active_profile_matches=cached_value.get("profile_matches", []),
        indicators=signals,
        last_close=float(meta.get("last_price", 0.0)),
        atr_pct=float(meta.get("atr_pct", 0.0)),
    )

    # Price vs EMA context
    agg.price_vs_ema21 = _pct_vs_indicator(signals, "ema_stack", agg.last_close)
    agg.price_vs_ema200 = _pct_vs_indicator(signals, "ema_stack", agg.last_close, key="200")

    # S/R levels from signals (Fibonacci/Pivot)
    fib_val = signals.get("fibonacci", 0.0)
    pivot_val = signals.get("pivot_points", 0.0)
    if fib_val > 0 or pivot_val > 0:
        agg.entry_zone = agg.last_close
        atr = float(meta.get("atr", 0.0))
        if atr > 0:
            agg.stop_level = round(agg.last_close - 1.5 * atr, 4)
            agg.target_level = round(agg.last_close + 2.0 * atr, 4)
            if agg.stop_level and agg.entry_zone and agg.target_level:
                risk = agg.entry_zone - agg.stop_level
                if risk > 0:
                    agg.risk_reward_ratio = round((agg.target_level - agg.entry_zone) / risk, 2)

    # YOLOv8 chart patterns
    pattern_result = await db.execute(
        select(PatternDetection)
        .where(PatternDetection.symbol_id == symbol_id)
        .order_by(desc(PatternDetection.detected_at))
        .limit(5)
    )
    for p in pattern_result.scalars().all():
        agg.chart_patterns.append(
            {
                "name": p.pattern_name,
                "confidence": float(p.confidence),
                "direction": p.direction.value
                if hasattr(p.direction, "value")
                else str(p.direction),
            }
        )

    # Elliott Wave from signals
    ew_quality = signals.get("ew_ratio_quality", 0.0)
    if ew_quality > 0.1:
        w3 = signals.get("ew_wave3_active", 0.0)
        w5 = signals.get("ew_wave5_active", 0.0)
        abc = signals.get("ew_corrective_abc", 0.0)
        if w3 > 0.5:
            agg.ew_summary = "Wave 3 of impulse (high confidence)"
        elif w5 > 0.3:
            agg.ew_summary = "Wave 5 of impulse"
        elif abc < -0.1:
            agg.ew_summary = "ABC corrective pattern"
        else:
            agg.ew_summary = f"Elliott Wave detected (quality: {ew_quality:.0%})"

    # Chronos-2 forecast
    forecast_result = await db.execute(
        select(ForecastCache)
        .where(ForecastCache.symbol_id == symbol_id)
        .order_by(desc(ForecastCache.generated_at))
        .limit(1)
    )
    forecast_row = forecast_result.scalar_one_or_none()
    if forecast_row is not None:
        agg.forecast_direction = forecast_row.direction
        agg.forecast_expected_move_pct = float(forecast_row.expected_move_pct)
        agg.forecast_confidence = float(forecast_row.direction_confidence)
        q10 = forecast_row.quantile_10
        q90 = forecast_row.quantile_90
        if q10 and q90:
            agg.forecast_range_low = round(q10[-1], 2) if q10 else None
            agg.forecast_range_high = round(q90[-1], 2) if q90 else None

    return agg


def _pct_vs_indicator(
    signals: dict[str, float],
    indicator: str,
    last_close: float,
    key: str = "21",
) -> float:
    """Estimate price vs EMA from signal values. Returns 0.0 if unavailable."""
    # The ema_stack signal is a composite; we approximate from the signal value
    val = signals.get(indicator, 0.0)
    # Positive ema_stack = price above EMAs, negative = below
    # Scale to rough percentage (signal is -1 to +1, map to approx -10% to +10%)
    return round(val * 10.0, 2)
