"""
Momentum indicators: RSI, MACD, Stochastic.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _zone_normalize(
    value: float,
    low_bullish: float,
    low_threshold: float,
    high_threshold: float,
    high_bearish: float,
) -> float:
    """Zone-based normalization for oscillators (0-100 scale)."""
    if value <= low_bullish:
        return 1.0
    if value <= low_threshold:
        # Interpolate between low_bullish (1.0) and low_threshold (0.3)
        t = (value - low_bullish) / (low_threshold - low_bullish)
        return 1.0 - t * (1.0 - 0.3)
    if value < high_threshold:
        # Neutral zone: linear from +0.3 to -0.3
        t = (value - low_threshold) / (high_threshold - low_threshold)
        return 0.3 - t * 0.6
    if value < high_bearish:
        # Interpolate between high_threshold (-0.3) and high_bearish (-1.0)
        t = (value - high_threshold) / (high_bearish - high_threshold)
        return -0.3 - t * 0.7
    return -1.0


def _crossover_decay(series_a: pd.Series, series_b: pd.Series, decay_bars: int = 10) -> float:
    """
    Detect the most recent crossover between series_a and series_b.
    Returns ±1 * (1 - bars_since / decay_bars). 0 if no recent cross.
    """
    if len(series_a) < 2 or len(series_b) < 2:
        return 0.0
    for i in range(1, min(decay_bars + 1, len(series_a))):
        idx = -(i + 1)
        if series_a.iloc[idx] <= series_b.iloc[idx] and series_a.iloc[-i] > series_b.iloc[-i]:
            # Bullish cross: a crossed above b
            decay = max(0.0, 1.0 - (i - 1) / decay_bars)
            return decay
        if series_a.iloc[idx] >= series_b.iloc[idx] and series_a.iloc[-i] < series_b.iloc[-i]:
            # Bearish cross: a crossed below b
            decay = max(0.0, 1.0 - (i - 1) / decay_bars)
            return -decay
    return 0.0


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


def compute_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """Add rsi_14 column."""
    out = df.copy()
    try:
        out["rsi_14"] = ta.rsi(out["close"], length=14)
    except Exception:
        pass
    return out


def compute_rsi_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    RSI zone-based normalization:
    <= 20 → +1.0, <= 30 → +0.7→+1.0, neutral 30-70, >= 70 → -0.7→-1.0, >= 80 → -1.0
    """
    if len(df) < 20:
        return {}
    try:
        d = compute_rsi(df)
        rsi_val = d["rsi_14"].dropna()
        if rsi_val.empty:
            return {"rsi": 0.0}
        val = float(rsi_val.iloc[-1])
        score = _zone_normalize(val, 20.0, 30.0, 70.0, 80.0)
        return {"rsi": max(-1.0, min(1.0, score))}
    except Exception:
        return {"rsi": 0.0}


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


def compute_macd(df: pd.DataFrame) -> pd.DataFrame:
    """Add macd, macdh, macds columns."""
    out = df.copy()
    try:
        result = ta.macd(out["close"], fast=12, slow=26, signal=9)
        if result is not None and not result.empty:
            cols = result.columns.tolist()
            macd_col = next((c for c in cols if c.startswith("MACD_")), None)
            hist_col = next((c for c in cols if c.startswith("MACDh_")), None)
            sig_col = next((c for c in cols if c.startswith("MACDs_")), None)
            if macd_col:
                out["macd"] = result[macd_col]
            if hist_col:
                out["macdh"] = result[hist_col]
            if sig_col:
                out["macds"] = result[sig_col]
    except Exception:
        pass
    return out


def compute_macd_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    MACD sub-signals:
    1. Histogram sign: positive → +0.5
    2. Signal line cross: ±1 with 10-bar decay
    3. Zero-line position: MACD > 0 → +0.3
    Average of 3 sub-signals.
    """
    if len(df) < 30:
        return {}
    try:
        d = compute_macd(df)
        macd = d.get("macd", pd.Series(dtype=float))
        hist = d.get("macdh", pd.Series(dtype=float))
        sig = d.get("macds", pd.Series(dtype=float))

        if not isinstance(macd, pd.Series):
            macd = pd.Series(dtype=float)
        if not isinstance(hist, pd.Series):
            hist = pd.Series(dtype=float)
        if not isinstance(sig, pd.Series):
            sig = pd.Series(dtype=float)

        hist_clean = hist.dropna()
        macd_clean = macd.dropna()

        # Sub-signal 1: histogram sign
        if hist_clean.empty:
            hist_score = 0.0
        else:
            hist_score = 0.5 if float(hist_clean.iloc[-1]) > 0 else -0.5

        # Sub-signal 2: MACD/signal crossover with decay
        if len(macd_clean) >= 2 and len(sig.dropna()) >= 2:
            macd_s = macd_clean.dropna()
            sig_s = sig.dropna()
            min_len = min(len(macd_s), len(sig_s))
            cross_score = _crossover_decay(
                macd_s.iloc[-min_len:], sig_s.iloc[-min_len:], decay_bars=10
            )
        else:
            cross_score = 0.0

        # Sub-signal 3: zero-line position
        zero_score = 0.3 if (not macd_clean.empty and float(macd_clean.iloc[-1]) > 0) else -0.3

        combined = (hist_score + cross_score + zero_score) / 3.0
        return {"macd": max(-1.0, min(1.0, combined))}
    except Exception:
        return {"macd": 0.0}


# ---------------------------------------------------------------------------
# Stochastic
# ---------------------------------------------------------------------------


def compute_stoch(df: pd.DataFrame) -> pd.DataFrame:
    """Add stoch_k, stoch_d columns."""
    out = df.copy()
    try:
        result = ta.stoch(out["high"], out["low"], out["close"], k=14, d=3, smooth_k=3)
        if result is not None and not result.empty:
            cols = result.columns.tolist()
            k_col = next((c for c in cols if c.startswith("STOCHk_")), None)
            d_col = next((c for c in cols if c.startswith("STOCHd_")), None)
            if k_col:
                out["stoch_k"] = result[k_col]
            if d_col:
                out["stoch_d"] = result[d_col]
    except Exception:
        pass
    return out


def compute_stoch_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    Stochastic: zone position (same thresholds as RSI 20/80) + %K/%D cross with decay.
    """
    if len(df) < 20:
        return {}
    try:
        d = compute_stoch(df)
        k = d.get("stoch_k", pd.Series(dtype=float))
        dk = d.get("stoch_d", pd.Series(dtype=float))

        if not isinstance(k, pd.Series):
            k = pd.Series(dtype=float)
        if not isinstance(dk, pd.Series):
            dk = pd.Series(dtype=float)

        k_clean = k.dropna()
        dk_clean = dk.dropna()

        if k_clean.empty:
            return {"stochastic": 0.0}

        # Zone score
        zone_score = _zone_normalize(float(k_clean.iloc[-1]), 20.0, 30.0, 70.0, 80.0)

        # Cross score
        if len(k_clean) >= 2 and len(dk_clean) >= 2:
            min_len = min(len(k_clean), len(dk_clean))
            cross_score = _crossover_decay(
                k_clean.iloc[-min_len:], dk_clean.iloc[-min_len:], decay_bars=10
            )
        else:
            cross_score = 0.0

        combined = (zone_score + cross_score) / 2.0
        return {"stochastic": max(-1.0, min(1.0, combined))}
    except Exception:
        return {"stochastic": 0.0}
