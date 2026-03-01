"""
Signal aggregation and composite scoring for the analysis pipeline.

Imports composite_score and passes_filter from app.services.scoring (shared utilities).
"""

from __future__ import annotations

from app.services.scoring import composite_score, passes_filter

__all__ = [
    "composite_score",
    "passes_filter",
    "normalize_oscillator",
    "apply_decay",
    "aggregate_signals",
    "build_composite",
    "CATEGORY_MAP",
    "CATEGORY_WEIGHTS",
]

CATEGORY_MAP: dict[str, list[str]] = {
    "trend": ["ema_stack", "adx_dmi", "supertrend"],
    "momentum": ["rsi", "macd", "stochastic"],
    "volume": ["obv", "vwap", "cmf"],
    "volatility": ["bb_pct_b", "ttm_squeeze", "atr"],
    "support_resistance": ["fibonacci", "pivot_points"],
    "divergence": ["rsi_divergence", "macd_divergence"],
    "pattern": ["candlestick"],
}

CATEGORY_WEIGHTS: dict[str, float] = {
    "trend": 0.30,
    "momentum": 0.20,
    "volume": 0.15,
    "volatility": 0.10,
    "support_resistance": 0.10,
    "divergence": 0.10,
    "pattern": 0.05,
}


def normalize_oscillator(
    value: float,
    low_bullish: float,
    low_threshold: float,
    high_threshold: float,
    high_bearish: float,
) -> float:
    """
    Zone-based oscillator normalization.

    value <= low_bullish  → +1.0
    value in [low_bullish, low_threshold]  → interpolate +1.0 → +0.3
    value in [low_threshold, high_threshold]  → interpolate +0.3 → -0.3
    value in [high_threshold, high_bearish]  → interpolate -0.3 → -1.0
    value >= high_bearish  → -1.0
    """
    if value <= low_bullish:
        return 1.0
    if value >= high_bearish:
        return -1.0
    if value <= low_threshold:
        t = (value - low_bullish) / (low_threshold - low_bullish)
        return 1.0 - t * (1.0 - 0.3)
    if value < high_threshold:
        t = (value - low_threshold) / (high_threshold - low_threshold)
        return 0.3 - t * 0.6
    # high_threshold <= value < high_bearish
    t = (value - high_threshold) / (high_bearish - high_threshold)
    return -0.3 - t * 0.7


def apply_decay(value: float, bars_since_event: int, decay_bars: int) -> float:
    """
    Linear decay: 1.0×value at event_bar, 0.0 at event_bar + decay_bars.

    Parameters
    ----------
    value : float
        Signal strength at event bar.
    bars_since_event : int
        Number of bars since the event occurred.
    decay_bars : int
        Number of bars over which the signal decays to zero.
    """
    if decay_bars <= 0:
        return 0.0
    if bars_since_event <= 0:
        return value
    if bars_since_event >= decay_bars:
        return 0.0
    return value * (1.0 - bars_since_event / decay_bars)


def aggregate_signals(signals: dict[str, float]) -> dict[str, float]:
    """
    Average per-indicator signal scores into category scores.

    Only indicators present in ``signals`` contribute to the average (failed or
    insufficient-data indicators are excluded, not treated as 0.0).  A category
    where *all* indicators are missing returns 0.0.

    Returns a dict of category → mean_score.
    """
    category_scores: dict[str, float] = {}
    for category, indicators in CATEGORY_MAP.items():
        values = [signals[ind] for ind in indicators if ind in signals]
        category_scores[category] = sum(values) / len(values) if values else 0.0
    return category_scores


def build_composite(signals: dict[str, float]) -> tuple[dict[str, float], float]:
    """
    Build category scores and composite score from individual signal dict.

    The pattern category averages candlestick + harmonic_score when a harmonic
    pattern is detected; otherwise it uses candlestick only.

    Returns
    -------
    (category_scores, composite) : tuple[dict[str, float], float]
    """
    cats = aggregate_signals(signals)

    # Pattern category: conditional average — include harmonic_score only when detected
    pattern_signals = [signals.get("candlestick", 0.0)]
    if signals.get("harmonic_pattern_detected", 0.0) > 0.5:
        pattern_signals.append(signals.get("harmonic_score", 0.0))
    cats["pattern"] = sum(pattern_signals) / len(pattern_signals)

    comp = composite_score(cats, CATEGORY_WEIGHTS)
    return cats, comp
