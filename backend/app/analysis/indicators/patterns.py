"""
Candlestick pattern detection — pure pandas/numpy (no ta-lib required).

Patterns: Bullish Engulfing, Hammer, Shooting Star, Morning Star, Evening Star.

Context filter:
- Bullish patterns (Hammer, Morning Star): only score if Supertrend bearish OR close < ema_50
- Bearish patterns (Shooting Star, Evening Star): only score if Supertrend bullish OR close > ema_50

Score: ±1 at detection, decays to 0 over 5 bars.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta

_DECAY_BARS = 5


def _apply_decay(value: float, bars_since: int) -> float:
    if bars_since >= _DECAY_BARS:
        return 0.0
    return value * (1.0 - bars_since / _DECAY_BARS)


def _body_size(o: float, c: float) -> float:
    return abs(c - o)


def _upper_shadow(o: float, h: float, c: float) -> float:
    return h - max(o, c)


def _lower_shadow(o: float, l: float, c: float) -> float:
    return min(o, c) - l


def _total_range(h: float, l: float) -> float:
    return h - l


def _is_bearish(o: float, c: float) -> bool:
    return c < o


def _is_bullish(o: float, c: float) -> bool:
    return c > o


# ---------------------------------------------------------------------------
# Individual pattern detectors — return bars_since_signal or None
# ---------------------------------------------------------------------------

def _bullish_engulfing(df: pd.DataFrame, i: int) -> bool:
    """Current bar fully engulfs prior bearish bar."""
    if i < 1:
        return False
    prev_o = float(df["open"].iloc[i - 1])
    prev_c = float(df["close"].iloc[i - 1])
    curr_o = float(df["open"].iloc[i])
    curr_c = float(df["close"].iloc[i])
    return (
        _is_bearish(prev_o, prev_c)
        and curr_o <= prev_c
        and curr_c > prev_o
    )


def _hammer(df: pd.DataFrame, i: int) -> bool:
    """Hammer: small body, long lower shadow, short upper shadow."""
    o = float(df["open"].iloc[i])
    h = float(df["high"].iloc[i])
    l = float(df["low"].iloc[i])
    c = float(df["close"].iloc[i])
    rng = _total_range(h, l)
    if rng == 0:
        return False
    body = _body_size(o, c)
    upper = _upper_shadow(o, h, c)
    lower = _lower_shadow(o, l, c)
    return (
        body <= 0.30 * rng
        and lower >= 2.0 * body
        and upper <= 0.5 * body
    )


def _shooting_star(df: pd.DataFrame, i: int) -> bool:
    """Shooting star: small body, long upper shadow, short lower shadow."""
    o = float(df["open"].iloc[i])
    h = float(df["high"].iloc[i])
    l = float(df["low"].iloc[i])
    c = float(df["close"].iloc[i])
    rng = _total_range(h, l)
    if rng == 0:
        return False
    body = _body_size(o, c)
    upper = _upper_shadow(o, h, c)
    lower = _lower_shadow(o, l, c)
    return (
        body <= 0.30 * rng
        and upper >= 2.0 * body
        and lower <= 0.5 * body
    )


def _morning_star(df: pd.DataFrame, i: int) -> bool:
    """Morning Star: 3-bar pattern — large bearish + small body (gap) + large bullish."""
    if i < 2:
        return False
    o1 = float(df["open"].iloc[i - 2])
    c1 = float(df["close"].iloc[i - 2])
    h1 = float(df["high"].iloc[i - 2])
    l1 = float(df["low"].iloc[i - 2])
    o2 = float(df["open"].iloc[i - 1])
    c2 = float(df["close"].iloc[i - 1])
    o3 = float(df["open"].iloc[i])
    c3 = float(df["close"].iloc[i])

    bar1_body = _body_size(o1, c1)
    bar1_range = _total_range(h1, l1)
    bar2_body = _body_size(o2, c2)

    if bar1_range == 0:
        return False

    midpoint_bar1 = (o1 + c1) / 2.0

    return (
        _is_bearish(o1, c1)  # Bar 1: large bearish
        and bar1_body >= 0.5 * bar1_range
        and bar2_body <= 0.3 * bar1_body  # Bar 2: small body
        and _is_bullish(o3, c3)  # Bar 3: bullish
        and c3 > midpoint_bar1  # Close above midpoint of bar 1
    )


def _evening_star(df: pd.DataFrame, i: int) -> bool:
    """Evening Star: 3-bar inverse of Morning Star."""
    if i < 2:
        return False
    o1 = float(df["open"].iloc[i - 2])
    c1 = float(df["close"].iloc[i - 2])
    h1 = float(df["high"].iloc[i - 2])
    l1 = float(df["low"].iloc[i - 2])
    o2 = float(df["open"].iloc[i - 1])
    c2 = float(df["close"].iloc[i - 1])
    o3 = float(df["open"].iloc[i])
    c3 = float(df["close"].iloc[i])

    bar1_body = _body_size(o1, c1)
    bar1_range = _total_range(h1, l1)
    bar2_body = _body_size(o2, c2)

    if bar1_range == 0:
        return False

    midpoint_bar1 = (o1 + c1) / 2.0

    return (
        _is_bullish(o1, c1)  # Bar 1: large bullish
        and bar1_body >= 0.5 * bar1_range
        and bar2_body <= 0.3 * bar1_body  # Bar 2: small body
        and _is_bearish(o3, c3)  # Bar 3: bearish
        and c3 < midpoint_bar1  # Close below midpoint of bar 1
    )


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def _get_context(df: pd.DataFrame) -> tuple[bool | None, float | None]:
    """
    Returns (supertrend_is_bullish, ema_50_value) for the last bar.
    Either can be None if not computable.
    """
    supertrend_bullish: bool | None = None
    ema_50_val: float | None = None

    try:
        st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
        if st is not None and not st.empty:
            dir_col = next((c for c in st.columns if c.startswith("SUPERTd_")), None)
            if dir_col:
                val = st[dir_col].dropna()
                if not val.empty:
                    supertrend_bullish = float(val.iloc[-1]) > 0
    except Exception:
        pass

    try:
        ema50 = ta.ema(df["close"], length=50)
        if ema50 is not None:
            clean = ema50.dropna()
            if not clean.empty:
                ema_50_val = float(clean.iloc[-1])
    except Exception:
        pass

    return supertrend_bullish, ema_50_val


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_candlestick_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    Scan last `_DECAY_BARS` bars for candlestick patterns.
    Apply context filter. Return decayed score for the strongest recent signal.
    """
    if len(df) < 5:
        return {}
    try:
        supertrend_bullish, ema_50 = _get_context(df)
        close = float(df["close"].iloc[-1])

        best_score = 0.0
        n = len(df)

        for bars_ago in range(0, min(_DECAY_BARS, n)):
            i = n - 1 - bars_ago

            # --- Bullish patterns ---
            bullish_signal = False
            if _bullish_engulfing(df, i):
                bullish_signal = True
            if _hammer(df, i):
                bullish_signal = True
            if _morning_star(df, i):
                bullish_signal = True

            if bullish_signal:
                # Context filter: only score if Supertrend bearish OR close < ema_50
                context_ok = (
                    (supertrend_bullish is not None and not supertrend_bullish)
                    or (ema_50 is not None and close < ema_50)
                    or (supertrend_bullish is None and ema_50 is None)
                )
                if context_ok:
                    candidate = _apply_decay(1.0, bars_ago)
                    if abs(candidate) > abs(best_score):
                        best_score = candidate

            # --- Bearish patterns ---
            bearish_signal = False
            if _shooting_star(df, i):
                bearish_signal = True
            if _evening_star(df, i):
                bearish_signal = True

            if bearish_signal:
                # Context filter: only score if Supertrend bullish OR close > ema_50
                context_ok = (
                    (supertrend_bullish is not None and supertrend_bullish)
                    or (ema_50 is not None and close > ema_50)
                    or (supertrend_bullish is None and ema_50 is None)
                )
                if context_ok:
                    candidate = _apply_decay(-1.0, bars_ago)
                    if abs(candidate) > abs(best_score):
                        best_score = candidate

        return {"candlestick": max(-1.0, min(1.0, best_score))}
    except Exception:
        return {"candlestick": 0.0}
