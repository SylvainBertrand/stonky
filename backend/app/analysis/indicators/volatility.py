"""
Volatility indicators: Bollinger Bands, ATR, Keltner Channels, TTM Squeeze.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as ta


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def compute_bbands(df: pd.DataFrame) -> pd.DataFrame:
    """Add bbl, bbm, bbu, bbp columns (Bollinger Bands, 20-period, 2 std)."""
    out = df.copy()
    try:
        result = ta.bbands(out["close"], length=20, std=2.0)
        if result is not None and not result.empty:
            cols = result.columns.tolist()
            lower = next((c for c in cols if c.startswith("BBL_")), None)
            mid = next((c for c in cols if c.startswith("BBM_")), None)
            upper = next((c for c in cols if c.startswith("BBU_")), None)
            pct = next((c for c in cols if c.startswith("BBP_")), None)
            if lower:
                out["bbl"] = result[lower]
            if mid:
                out["bbm"] = result[mid]
            if upper:
                out["bbu"] = result[upper]
            if pct:
                out["bbp"] = result[pct]
    except Exception:
        pass
    return out


def compute_bbands_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    BB %B signal:
    %B < 0.2 → +0.7 (at lower band support)
    %B > 0.8 → -0.7 (at upper band resistance)
    Linear interpolation between 0.2 and 0.8.
    """
    if len(df) < 20:
        return {}
    try:
        d = compute_bbands(df)
        bbp = d.get("bbp", pd.Series(dtype=float))
        if not isinstance(bbp, pd.Series):
            bbp = pd.Series(dtype=float)
        bbp_clean = bbp.dropna()
        if bbp_clean.empty:
            return {"bb_pct_b": 0.0}
        val = float(bbp_clean.iloc[-1])
        if val <= 0.2:
            score = 0.7
        elif val >= 0.8:
            score = -0.7
        else:
            # Linear from +0.7 to -0.7 across [0.2, 0.8]
            t = (val - 0.2) / 0.6
            score = 0.7 - t * 1.4
        return {"bb_pct_b": max(-1.0, min(1.0, score))}
    except Exception:
        return {"bb_pct_b": 0.0}


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

def compute_atr(df: pd.DataFrame) -> pd.DataFrame:
    """Add atr column."""
    out = df.copy()
    try:
        out["atr"] = ta.atr(out["high"], out["low"], out["close"], length=14)
    except Exception:
        pass
    return out


def compute_atr_signals(df: pd.DataFrame) -> dict[str, float]:
    """ATR is a sizing tool — signal is always 0.0."""
    return {"atr": 0.0}


# ---------------------------------------------------------------------------
# Keltner Channels
# ---------------------------------------------------------------------------

def compute_keltner(df: pd.DataFrame) -> pd.DataFrame:
    """Add kcl, kcu columns (Keltner Channels, 20-period, 1.5 ATR scalar)."""
    out = df.copy()
    try:
        result = ta.kc(out["high"], out["low"], out["close"], length=20, scalar=1.5)
        if result is not None and not result.empty:
            cols = result.columns.tolist()
            lower = next((c for c in cols if c.startswith("KCLe_")), None)
            upper = next((c for c in cols if c.startswith("KCUe_")), None)
            if lower:
                out["kcl"] = result[lower]
            if upper:
                out["kcu"] = result[upper]
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# TTM Squeeze
# ---------------------------------------------------------------------------

def compute_ttm_squeeze(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute TTM Squeeze.
    Adds: squeeze_on (bool), squeeze_fired (bool), squeeze_momentum columns.
    """
    out = df.copy()
    try:
        out = compute_bbands(out)
        out = compute_keltner(out)

        bbl = out.get("bbl", pd.Series(dtype=float))
        bbu = out.get("bbu", pd.Series(dtype=float))
        kcl = out.get("kcl", pd.Series(dtype=float))
        kcu = out.get("kcu", pd.Series(dtype=float))

        if not isinstance(bbl, pd.Series):
            return out
        if not isinstance(kcl, pd.Series):
            return out

        squeeze_on = (bbl > kcl) & (bbu < kcu)
        squeeze_fired = squeeze_on.shift(1).fillna(False) & ~squeeze_on

        # Squeeze momentum: linear regression of close - midpoint(KC)
        mid_kc = (kcu + kcl) / 2.0
        delta = out["close"] - mid_kc

        momentum = pd.Series(np.nan, index=out.index)
        for i in range(19, len(delta)):
            y = delta.iloc[i - 19 : i + 1].to_numpy(dtype=float)
            x = np.arange(20, dtype=float)
            valid = ~np.isnan(y)
            if valid.sum() >= 10:
                coeffs = np.polyfit(x[valid], y[valid], 1)
                momentum.iloc[i] = coeffs[0]  # slope

        out["squeeze_on"] = squeeze_on
        out["squeeze_fired"] = squeeze_fired
        out["squeeze_momentum"] = momentum
    except Exception:
        pass
    return out


_TTM_DECAY_BARS = 10


def compute_ttm_squeeze_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    TTM Squeeze signal with 10-bar decay for recent fires:
    - squeeze fired within last 10 bars: ±1.0 at fire bar, decays linearly to 0
    - squeeze_on (building): -0.2 (potential energy)
    - no squeeze: map momentum slope to ±0.5

    This allows profile filters to detect "fired ≤3 bars ago" via score >= 0.7.
    """
    if len(df) < 25:
        return {}
    try:
        d = compute_ttm_squeeze(df)
        if "squeeze_on" not in d.columns:
            return {"ttm_squeeze": 0.0}

        n = len(d)

        # Scan back through last decay_bars for the most recent fire
        for bars_ago in range(min(_TTM_DECAY_BARS, n)):
            row = d.iloc[-(bars_ago + 1)]
            fired = bool(row.get("squeeze_fired", False))
            if fired:
                momentum = float(row.get("squeeze_momentum", 0.0) or 0.0)
                direction = 1.0 if momentum > 0 else -1.0
                score = direction * (1.0 - bars_ago / _TTM_DECAY_BARS)
                return {"ttm_squeeze": max(-1.0, min(1.0, score))}

        # No recent fire — check if currently in squeeze (potential energy)
        row = d.iloc[-1]
        on = bool(row.get("squeeze_on", False))
        momentum = float(row.get("squeeze_momentum", 0.0) or 0.0)

        if on:
            score = -0.2
        else:
            # No squeeze: map momentum slope to ±0.5
            if np.isnan(momentum):
                score = 0.0
            else:
                atr_vals = d.get("atr", pd.Series(dtype=float))
                if not isinstance(atr_vals, pd.Series):
                    atr_vals = pd.Series(dtype=float)
                atr_clean = atr_vals.dropna()
                if not atr_clean.empty and float(atr_clean.iloc[-1]) > 0:
                    normalized = momentum / float(atr_clean.iloc[-1])
                    score = max(-0.5, min(0.5, normalized))
                else:
                    score = 0.0

        return {"ttm_squeeze": max(-1.0, min(1.0, score))}
    except Exception:
        return {"ttm_squeeze": 0.0}
