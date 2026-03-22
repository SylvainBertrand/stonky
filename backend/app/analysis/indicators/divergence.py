"""
Divergence indicators: RSI Divergence, MACD Histogram Divergence.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta

from app.analysis.swing_points import detect_swing_points

_LOOKBACK = 50
_DECAY_BARS = 20
_PRICE_TOL_ATR = 1.0  # price pivots within 1 ATR are "similar"
_OSC_TOL_PCT = 0.05  # oscillator pivots within 5% are "similar"


def _get_atr(df: pd.DataFrame) -> float:
    try:
        atr = ta.atr(df["high"], df["low"], df["close"], length=14)
        if atr is not None:
            clean = atr.dropna()
            if not clean.empty:
                return float(clean.iloc[-1])
    except Exception:
        pass
    return 0.0


def _apply_decay(value: float, bars_since: int, decay_bars: int) -> float:
    if bars_since >= decay_bars:
        return 0.0
    return value * (1.0 - bars_since / decay_bars)


def _find_recent_same_type_pivots(
    series: pd.Series,
    pivot_mask: pd.Series,
    lookback: int,
) -> list[tuple[int, float]]:
    """Return list of (position, value) for the last `lookback` bars where pivot_mask is True."""
    end = len(series)
    start = max(0, end - lookback)
    result = []
    for i in range(start, end):
        if pivot_mask.iloc[i]:
            result.append((i, float(series.iloc[i])))
    return result


def _detect_divergence(
    price: pd.Series,
    oscillator: pd.Series,
    atr_val: float,
    lookback: int = _LOOKBACK,
) -> dict[str, int]:
    """
    Compare last 2 swing highs and swing lows in price vs oscillator.
    Returns dict of divergence type → bars_since_event (0 if just detected).
    """
    results: dict[str, int] = {}

    price_highs, price_lows = detect_swing_points(price, order=3, atr_filter=0.0)
    osc_highs, osc_lows = detect_swing_points(oscillator, order=3, atr_filter=0.0)

    price_high_pts = _find_recent_same_type_pivots(price, price_highs, lookback)
    price_low_pts = _find_recent_same_type_pivots(price, price_lows, lookback)
    osc_high_pts = _find_recent_same_type_pivots(oscillator, osc_highs, lookback)
    osc_low_pts = _find_recent_same_type_pivots(oscillator, osc_lows, lookback)

    n = len(price)

    # Check bearish divergence: price HH + oscillator LH (regular bearish)
    if len(price_high_pts) >= 2 and len(osc_high_pts) >= 2:
        ph1_idx, ph1_val = price_high_pts[-2]
        ph2_idx, ph2_val = price_high_pts[-1]
        oh1_idx, oh1_val = osc_high_pts[-2]
        oh2_idx, oh2_val = osc_high_pts[-1]
        if ph2_val > ph1_val * (1 + _OSC_TOL_PCT):  # price HH
            if oh2_val < oh1_val * (1 - _OSC_TOL_PCT):  # osc LH
                bars_since = n - 1 - ph2_idx
                results["regular_bearish"] = bars_since

    # Check bullish divergence: price LL + oscillator HL (regular bullish)
    if len(price_low_pts) >= 2 and len(osc_low_pts) >= 2:
        pl1_idx, pl1_val = price_low_pts[-2]
        pl2_idx, pl2_val = price_low_pts[-1]
        ol1_idx, ol1_val = osc_low_pts[-2]
        ol2_idx, ol2_val = osc_low_pts[-1]
        if pl2_val < pl1_val * (1 - _OSC_TOL_PCT):  # price LL
            if ol2_val > ol1_val * (1 + _OSC_TOL_PCT):  # osc HL
                bars_since = n - 1 - pl2_idx
                results["regular_bullish"] = bars_since

    # Hidden bullish: price HL + oscillator LL
    if len(price_low_pts) >= 2 and len(osc_low_pts) >= 2:
        pl1_idx, pl1_val = price_low_pts[-2]
        pl2_idx, pl2_val = price_low_pts[-1]
        ol1_idx, ol1_val = osc_low_pts[-2]
        ol2_idx, ol2_val = osc_low_pts[-1]
        if pl2_val > pl1_val * (1 + _OSC_TOL_PCT):  # price HL
            if ol2_val < ol1_val * (1 - _OSC_TOL_PCT):  # osc LL
                bars_since = n - 1 - pl2_idx
                results["hidden_bullish"] = bars_since

    # Hidden bearish: price LH + oscillator HH
    if len(price_high_pts) >= 2 and len(osc_high_pts) >= 2:
        ph1_idx, ph1_val = price_high_pts[-2]
        ph2_idx, ph2_val = price_high_pts[-1]
        oh1_idx, oh1_val = osc_high_pts[-2]
        oh2_idx, oh2_val = osc_high_pts[-1]
        if ph2_val < ph1_val * (1 - _OSC_TOL_PCT):  # price LH
            if oh2_val > oh1_val * (1 + _OSC_TOL_PCT):  # osc HH
                bars_since = n - 1 - ph2_idx
                results["hidden_bearish"] = bars_since

    return results


# ---------------------------------------------------------------------------
# RSI Divergence
# ---------------------------------------------------------------------------


def compute_rsi_divergence_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    RSI divergence detection with 20-bar decay.
    Regular bullish → +1.0, regular bearish → -1.0
    Hidden bullish → +0.7, hidden bearish → -0.7
    """
    if len(df) < 30:
        return {}
    try:
        rsi = ta.rsi(df["close"], length=14)
        if rsi is None:
            return {"rsi_divergence": 0.0}
        rsi_clean = rsi.dropna()
        if len(rsi_clean) < 20:
            return {"rsi_divergence": 0.0}

        atr_val = _get_atr(df)
        price_aligned = df["close"].iloc[-len(rsi_clean) :]
        divergences = _detect_divergence(price_aligned, rsi_clean, atr_val)

        score = 0.0
        if "regular_bullish" in divergences:
            score = max(score, _apply_decay(1.0, divergences["regular_bullish"], _DECAY_BARS))
        if "regular_bearish" in divergences:
            candidate = _apply_decay(-1.0, divergences["regular_bearish"], _DECAY_BARS)
            if abs(candidate) > abs(score):
                score = candidate
        if "hidden_bullish" in divergences:
            candidate = _apply_decay(0.7, divergences["hidden_bullish"], _DECAY_BARS)
            if abs(candidate) > abs(score):
                score = candidate
        if "hidden_bearish" in divergences:
            candidate = _apply_decay(-0.7, divergences["hidden_bearish"], _DECAY_BARS)
            if abs(candidate) > abs(score):
                score = candidate

        return {"rsi_divergence": max(-1.0, min(1.0, score))}
    except Exception:
        return {"rsi_divergence": 0.0}


# ---------------------------------------------------------------------------
# MACD Histogram Divergence
# ---------------------------------------------------------------------------


def compute_macd_divergence_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    MACD histogram divergence detection with 20-bar decay.
    Same divergence types as RSI divergence.
    """
    if len(df) < 40:
        return {}
    try:
        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd_df is None or macd_df.empty:
            return {"macd_divergence": 0.0}

        # Get histogram column
        hist_col = next((c for c in macd_df.columns if c.startswith("MACDh_")), None)
        if hist_col is None:
            return {"macd_divergence": 0.0}

        hist = macd_df[hist_col].dropna()
        if len(hist) < 20:
            return {"macd_divergence": 0.0}

        atr_val = _get_atr(df)
        price_aligned = df["close"].iloc[-len(hist) :]
        divergences = _detect_divergence(price_aligned, hist, atr_val)

        score = 0.0
        if "regular_bullish" in divergences:
            score = max(score, _apply_decay(1.0, divergences["regular_bullish"], _DECAY_BARS))
        if "regular_bearish" in divergences:
            candidate = _apply_decay(-1.0, divergences["regular_bearish"], _DECAY_BARS)
            if abs(candidate) > abs(score):
                score = candidate
        if "hidden_bullish" in divergences:
            candidate = _apply_decay(0.7, divergences["hidden_bullish"], _DECAY_BARS)
            if abs(candidate) > abs(score):
                score = candidate
        if "hidden_bearish" in divergences:
            candidate = _apply_decay(-0.7, divergences["hidden_bearish"], _DECAY_BARS)
            if abs(candidate) > abs(score):
                score = candidate

        return {"macd_divergence": max(-1.0, min(1.0, score))}
    except Exception:
        return {"macd_divergence": 0.0}
