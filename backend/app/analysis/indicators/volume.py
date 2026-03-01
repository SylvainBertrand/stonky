"""
Volume indicators: OBV, Anchored VWAP, CMF.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as ta

from app.analysis.swing_points import detect_swing_points


# ---------------------------------------------------------------------------
# OBV
# ---------------------------------------------------------------------------

def compute_obv(df: pd.DataFrame) -> pd.DataFrame:
    """Add obv column."""
    out = df.copy()
    try:
        out["obv"] = ta.obv(out["close"], out["volume"])
    except Exception:
        pass
    return out


def compute_obv_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    OBV slope via np.polyfit over last 20 bars, normalized by median OBV.
    Positive slope → score proportional to magnitude, clamped to ±1.
    """
    if len(df) < 20:
        return {}
    try:
        d = compute_obv(df)
        obv = d.get("obv", pd.Series(dtype=float))
        if not isinstance(obv, pd.Series):
            obv = pd.Series(dtype=float)
        obv_clean = obv.dropna()
        if len(obv_clean) < 20:
            return {"obv": 0.0}
        recent = obv_clean.iloc[-20:].to_numpy(dtype=float)
        x = np.arange(20, dtype=float)
        coeffs = np.polyfit(x, recent, 1)
        slope = coeffs[0]
        median_obv = float(np.median(np.abs(recent)))
        if median_obv == 0:
            return {"obv": 0.0}
        normalized = slope / median_obv
        score = max(-1.0, min(1.0, normalized * 20.0))  # scale factor
        return {"obv": score}
    except Exception:
        return {"obv": 0.0}


# ---------------------------------------------------------------------------
# Anchored VWAP
# ---------------------------------------------------------------------------

def _compute_anchored_vwap(df: pd.DataFrame, anchor_idx: int) -> pd.Series:
    """Compute cumulative TVWAP anchored to anchor_idx."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].astype(float)
    cum_tv = (typical * vol).iloc[anchor_idx:].cumsum()
    cum_v = vol.iloc[anchor_idx:].cumsum()
    vwap = cum_tv / cum_v.replace(0, np.nan)
    return vwap


def compute_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Add session_vwap and anchored_vwap columns."""
    out = df.copy()
    try:
        # Session VWAP
        out["session_vwap"] = ta.vwap(out["high"], out["low"], out["close"], out["volume"])
    except Exception:
        pass

    try:
        # Anchored VWAP: anchor to most recent swing low
        out = compute_atr_for_vwap(out)
        atr_series = out.get("atr_vwap", None)
        _, swing_lows = detect_swing_points(
            out["close"], order=5,
            atr_filter=0.5,
            atr_series=atr_series if isinstance(atr_series, pd.Series) else None,
        )
        low_indices = swing_lows[swing_lows].index
        if len(low_indices) > 0:
            anchor_label = low_indices[-1]
            anchor_pos = out.index.get_loc(anchor_label)
            if isinstance(anchor_pos, int):
                anchored = _compute_anchored_vwap(out, anchor_pos)
                out["anchored_vwap"] = anchored
    except Exception:
        pass
    return out


def compute_atr_for_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Add atr_vwap column (ATR-14) for use in VWAP calculation."""
    out = df.copy()
    try:
        out["atr_vwap"] = ta.atr(out["high"], out["low"], out["close"], length=14)
    except Exception:
        pass
    return out


def compute_vwap_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    VWAP signal: (close - anchored_vwap) / ATR, mapped to ±1 (clamped at ±2 ATR).
    """
    if len(df) < 20:
        return {}
    try:
        d = compute_vwap(df)
        close = float(d["close"].iloc[-1])

        anchored = d.get("anchored_vwap", pd.Series(dtype=float))
        if isinstance(anchored, pd.Series) and not anchored.dropna().empty:
            anchored_val = float(anchored.dropna().iloc[-1])
        else:
            # Fall back to session VWAP
            sess = d.get("session_vwap", pd.Series(dtype=float))
            if not isinstance(sess, pd.Series) or sess.dropna().empty:
                return {"vwap": 0.0}
            anchored_val = float(sess.dropna().iloc[-1])

        atr_series = d.get("atr_vwap", pd.Series(dtype=float))
        if not isinstance(atr_series, pd.Series):
            atr_series = pd.Series(dtype=float)
        atr_clean = atr_series.dropna()
        if atr_clean.empty or float(atr_clean.iloc[-1]) == 0:
            return {"vwap": 0.0}

        atr_val = float(atr_clean.iloc[-1])
        deviation = (close - anchored_val) / atr_val
        score = max(-1.0, min(1.0, deviation / 2.0))
        return {"vwap": score}
    except Exception:
        return {"vwap": 0.0}


# ---------------------------------------------------------------------------
# CMF
# ---------------------------------------------------------------------------

def compute_cmf(df: pd.DataFrame) -> pd.DataFrame:
    """Add cmf column."""
    out = df.copy()
    try:
        out["cmf"] = ta.cmf(out["high"], out["low"], out["close"], out["volume"], length=20)
    except Exception:
        pass
    return out


def compute_cmf_signals(df: pd.DataFrame) -> dict[str, float]:
    """CMF is already in [-1, 1] — direct map."""
    if len(df) < 20:
        return {}
    try:
        d = compute_cmf(df)
        cmf = d.get("cmf", pd.Series(dtype=float))
        if not isinstance(cmf, pd.Series):
            cmf = pd.Series(dtype=float)
        cmf_clean = cmf.dropna()
        if cmf_clean.empty:
            return {"cmf": 0.0}
        val = float(cmf_clean.iloc[-1])
        return {"cmf": max(-1.0, min(1.0, val))}
    except Exception:
        return {"cmf": 0.0}
