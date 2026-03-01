"""
Signal normalization and composite scoring for the scanner pipeline.

Every indicator emits a score in [-1.0, 1.0]:
  +1.0 = maximally bullish
  -1.0 = maximally bearish
   0.0 = neutral

The composite score is a weighted average across 7 categories.
"""

from __future__ import annotations


def normalize_rsi(rsi: float) -> float:
    """
    Map RSI (0–100) to a score in [-1.0, 1.0].

    RSI < 50  → positive (bullish): oversold conditions
    RSI > 50  → negative (bearish): overbought conditions
    RSI = 50  → 0.0 (neutral)
    """
    raw = (50.0 - rsi) / 50.0
    return max(-1.0, min(1.0, raw))


def composite_score(
    category_scores: dict[str, float],
    weights: dict[str, float],
) -> float:
    """
    Compute weighted average of category scores.

    Only categories present in both dicts contribute.
    Returns 0.0 if total weight is zero.
    """
    weighted_sum = 0.0
    total_weight = 0.0
    for category, score in category_scores.items():
        weight = weights.get(category, 0.0)
        weighted_sum += score * weight
        total_weight += weight
    if total_weight == 0.0:
        return 0.0
    return weighted_sum / total_weight


def passes_filter(
    category_scores: dict[str, float],
    min_categories_agreeing: int,
) -> bool:
    """
    Return True if at least `min_categories_agreeing` categories have a positive score.

    A positive score means bullish agreement for that category.
    """
    agreeing = sum(1 for score in category_scores.values() if score > 0)
    return agreeing >= min_categories_agreeing
