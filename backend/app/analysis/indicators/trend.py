"""
Trend indicators: EMA stack, ADX/DMI, Supertrend.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta

# ---------------------------------------------------------------------------
# compute_ema
# ---------------------------------------------------------------------------


def compute_ema(df: pd.DataFrame) -> pd.DataFrame:
    """Add ema_21, ema_50, ema_200 columns."""
    out = df.copy()
    for length in (21, 50, 200):
        result = ta.ema(out["close"], length=length)
        out[f"ema_{length}"] = result
    return out


def compute_ema_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    EMA stack signal: count EMAs price is above.
    0/1/2/3 EMAs above → maps to -1 / -0.33 / +0.33 / +1.
    """
    if len(df) < 20:
        return {}
    try:
        d = compute_ema(df)
        close = float(d["close"].iloc[-1])
        mapping = {0: -1.0, 1: -0.33, 2: 0.33, 3: 1.0}
        above = 0
        for length in (21, 50, 200):
            col = f"ema_{length}"
            val = d[col].iloc[-1]
            if pd.notna(val) and close > float(val):
                above += 1
        return {"ema_stack": mapping[above]}
    except Exception:
        return {"ema_stack": 0.0}


# ---------------------------------------------------------------------------
# compute_adx
# ---------------------------------------------------------------------------


def compute_adx(df: pd.DataFrame) -> pd.DataFrame:
    """Add adx, dmp_14, dmn_14 columns (ADX-14)."""
    out = df.copy()
    try:
        result = ta.adx(out["high"], out["low"], out["close"], length=14)
        if result is not None and not result.empty:
            # pandas_ta column names: ADX_14, DMP_14, DMN_14
            cols = result.columns.tolist()
            adx_col = next((c for c in cols if c.startswith("ADX_")), None)
            dmp_col = next((c for c in cols if c.startswith("DMP_")), None)
            dmn_col = next((c for c in cols if c.startswith("DMN_")), None)
            if adx_col:
                out["adx"] = result[adx_col]
            if dmp_col:
                out["dmp_14"] = result[dmp_col]
            if dmn_col:
                out["dmn_14"] = result[dmn_col]
    except Exception:
        pass
    return out


def compute_adx_signals(df: pd.DataFrame) -> dict[str, float]:
    """
    ADX signal:
    - ADX < 20 → near 0 (ranging)
    - ADX >= 20 → sign from DI+/DI-, magnitude from ADX (20→0.0, 40→1.0 scale, capped)
    """
    if len(df) < 20:
        return {}
    try:
        d = compute_adx(df)
        row = d.iloc[-1]
        adx = float(row.get("adx", 0) or 0)
        dmp = float(row.get("dmp_14", 0) or 0)
        dmn = float(row.get("dmn_14", 0) or 0)
        if adx < 20:
            return {"adx_dmi": 0.0}
        direction = 1.0 if dmp > dmn else -1.0
        magnitude = min(1.0, (adx - 20.0) / 20.0)
        return {"adx_dmi": direction * magnitude}
    except Exception:
        return {"adx_dmi": 0.0}


# ---------------------------------------------------------------------------
# compute_supertrend
# ---------------------------------------------------------------------------


def compute_supertrend(df: pd.DataFrame) -> pd.DataFrame:
    """Add supertrend_dir column: +1 = bullish, -1 = bearish."""
    out = df.copy()
    try:
        result = ta.supertrend(out["high"], out["low"], out["close"], length=10, multiplier=3.0)
        if result is not None and not result.empty:
            # Direction column: SUPERTd_10_3.0
            dir_col = next((c for c in result.columns if c.startswith("SUPERTd_")), None)
            if dir_col:
                out["supertrend_dir"] = result[dir_col]
    except Exception:
        pass
    return out


def compute_supertrend_signals(df: pd.DataFrame) -> dict[str, float]:
    """Supertrend signal: binary +1 (bullish) or -1 (bearish)."""
    if len(df) < 20:
        return {}
    try:
        d = compute_supertrend(df)
        val = d["supertrend_dir"].dropna()
        if val.empty:
            return {"supertrend": 0.0}
        direction = float(val.iloc[-1])
        return {"supertrend": 1.0 if direction > 0 else -1.0}
    except Exception:
        return {"supertrend": 0.0}
