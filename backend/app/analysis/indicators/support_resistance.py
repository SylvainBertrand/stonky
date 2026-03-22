"""
Support / Resistance indicators: Fibonacci retracement, Pivot Points.
"""

from __future__ import annotations

import math

import pandas as pd
import pandas_ta as ta

from app.analysis.swing_points import detect_swing_points

# Fibonacci levels (ratio → quality weight)
_FIB_LEVELS: list[tuple[float, float]] = [
    (0.236, 0.4),
    (0.382, 0.6),
    (0.500, 0.8),
    (0.618, 1.0),
    (0.786, 0.4),
]

_PROXIMITY_ATR = 0.5  # max ATR distance to consider "at level"


def _get_atr(df: pd.DataFrame) -> float:
    """Return last ATR-14 value, or 0 on failure."""
    try:
        atr = ta.atr(df["high"], df["low"], df["close"], length=14)
        if atr is not None:
            clean = atr.dropna()
            if not clean.empty:
                return float(clean.iloc[-1])
    except Exception:
        pass
    return 0.0


# ---------------------------------------------------------------------------
# Fibonacci
# ---------------------------------------------------------------------------


def compute_fibonacci_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    Find most recent swing high/low pair, compute fib levels,
    detect nearest level within 0.5 ATR.
    """
    if len(df) < 20:
        return {}
    try:
        atr_val = _get_atr(df)
        if atr_val == 0.0:
            return {"fibonacci": 0.0}

        swing_highs, swing_lows = detect_swing_points(df["close"], order=5, atr_filter=0.0)
        high_indices = swing_highs[swing_highs].index.tolist()
        low_indices = swing_lows[swing_lows].index.tolist()

        if not high_indices or not low_indices:
            return {"fibonacci": 0.0}

        # Most recent swing pair
        last_high_pos = df.index.get_loc(high_indices[-1])
        last_low_pos = df.index.get_loc(low_indices[-1])

        if not isinstance(last_high_pos, int):
            return {"fibonacci": 0.0}
        if not isinstance(last_low_pos, int):
            return {"fibonacci": 0.0}

        swing_high_price = float(df["close"].iloc[last_high_pos])
        swing_low_price = float(df["close"].iloc[last_low_pos])
        close = float(df["close"].iloc[-1])

        if swing_high_price <= swing_low_price:
            return {"fibonacci": 0.0}

        swing_range = swing_high_price - swing_low_price
        is_downswing = last_high_pos > last_low_pos  # high came after low

        best_score = 0.0
        for ratio, quality in _FIB_LEVELS:
            level = swing_low_price + ratio * swing_range
            distance = abs(close - level)
            if distance <= _PROXIMITY_ATR * atr_val:
                # Determine if level is support or resistance
                if is_downswing:
                    # Retracing down: fib levels act as support below current price
                    sign = 1.0 if close > level else -1.0
                else:
                    # Bouncing up from low: fib levels act as resistance above
                    sign = -1.0 if close < level else 1.0
                score = sign * quality
                if abs(score) > abs(best_score):
                    best_score = score

        return {"fibonacci": max(-1.0, min(1.0, best_score))}
    except Exception:
        return {"fibonacci": 0.0}


# ---------------------------------------------------------------------------
# Pivot Points
# ---------------------------------------------------------------------------


def compute_pivot_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    Pivot points from previous bar's H/L/C.
    PP=(H+L+C)/3, S1-S3, R1-R3.
    Score = ±quality_weight × exp(-distance_in_atrs).
    """
    if len(df) < 2:
        return {}
    try:
        atr_val = _get_atr(df)
        if atr_val == 0.0:
            return {"pivot_points": 0.0}

        prev = df.iloc[-2]
        h = float(prev["high"])
        l = float(prev["low"])
        c = float(prev["close"])

        pp = (h + l + c) / 3.0
        r1 = 2 * pp - l
        r2 = pp + (h - l)
        r3 = h + 2 * (pp - l)
        s1 = 2 * pp - h
        s2 = pp - (h - l)
        s3 = l - 2 * (h - pp)

        close = float(df["close"].iloc[-1])

        # (level, is_support, quality_weight)
        levels: list[tuple[float, bool, float]] = [
            (r1, False, 0.7),
            (r2, False, 0.9),
            (r3, False, 1.0),
            (s1, True, 0.7),
            (s2, True, 0.9),
            (s3, True, 1.0),
            (pp, close < pp, 0.5),  # PP acts as support below, resistance above
        ]

        best_score = 0.0
        for level, is_support, quality in levels:
            distance_atrs = abs(close - level) / atr_val
            proximity = math.exp(-distance_atrs)
            sign = 1.0 if is_support else -1.0
            score = sign * quality * proximity
            if abs(score) > abs(best_score):
                best_score = score

        return {"pivot_points": max(-1.0, min(1.0, best_score))}
    except Exception:
        return {"pivot_points": 0.0}
