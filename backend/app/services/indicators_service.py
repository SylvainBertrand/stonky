"""
Raw indicator values service.

Computes the latest-bar numeric values for the indicators consumed by the
Technical Analyst agent. This is a *presentation layer* helper — it re-uses
the existing computation functions in `app.analysis.indicators.*` and pulls
the most recent value from each output column.

Returns a flat dict mapping indicator name → float (or None if the
underlying series has insufficient data / failed to compute). Designed to
be called from a thread pool via `loop.run_in_executor` so the FastAPI
event loop is never blocked.
"""

from __future__ import annotations

import logging

import pandas as pd

from app.analysis.indicators.momentum import compute_macd, compute_rsi
from app.analysis.indicators.trend import compute_ema
from app.analysis.indicators.volatility import compute_atr, compute_bbands
from app.analysis.indicators.volume import compute_obv, compute_vwap

logger = logging.getLogger(__name__)


# Bars needed before EMA-200 produces values. Indicator endpoints should fetch
# at least this many bars from the DB.
MIN_BARS_FOR_EMA200 = 200


def _last_value(df: pd.DataFrame, column: str) -> float | None:
    """Return the most recent non-NaN float in `column`, or None."""
    if column not in df.columns:
        return None
    series = df[column]
    if not isinstance(series, pd.Series):
        return None
    clean = series.dropna()
    if clean.empty:
        return None
    return round(float(clean.iloc[-1]), 6)


def compute_latest_indicators(df: pd.DataFrame) -> dict[str, float | None]:
    """
    Compute the latest-bar values for the full Technical Analyst indicator set.

    Args:
        df: OHLCV DataFrame with columns: open, high, low, close, volume.
            Should contain at least 200 bars for EMA-200 to populate.

    Returns:
        Flat dict mapping indicator name → float | None. Indicators that
        cannot be computed (insufficient bars, NaN, or pandas-ta failure)
        return None rather than raising.
    """
    out: dict[str, float | None] = {}

    # ── RSI ─────────────────────────────────────────────────────────────────
    rsi_df = compute_rsi(df)
    out["rsi"] = _last_value(rsi_df, "rsi_14")

    # ── MACD ────────────────────────────────────────────────────────────────
    macd_df = compute_macd(df)
    out["macd_line"] = _last_value(macd_df, "macd")
    out["macd_signal"] = _last_value(macd_df, "macds")
    out["macd_hist"] = _last_value(macd_df, "macdh")

    # ── Bollinger Bands (+ derived width) ───────────────────────────────────
    bb_df = compute_bbands(df)
    bb_upper = _last_value(bb_df, "bbu")
    bb_mid = _last_value(bb_df, "bbm")
    bb_lower = _last_value(bb_df, "bbl")
    out["bb_upper"] = bb_upper
    out["bb_mid"] = bb_mid
    out["bb_lower"] = bb_lower
    out["bb_pct_b"] = _last_value(bb_df, "bbp")
    if bb_upper is not None and bb_lower is not None and bb_mid:
        out["bb_width"] = round((bb_upper - bb_lower) / bb_mid, 6)
    else:
        out["bb_width"] = None

    # ── VWAP (session) ──────────────────────────────────────────────────────
    vwap_df = compute_vwap(df)
    out["vwap"] = _last_value(vwap_df, "session_vwap")

    # ── ATR (+ ATR % of close) ──────────────────────────────────────────────
    atr_df = compute_atr(df)
    atr = _last_value(atr_df, "atr")
    out["atr"] = atr
    last_close: float | None = None
    if "close" in df.columns and not df["close"].dropna().empty:
        last_close = float(df["close"].dropna().iloc[-1])
    if atr is not None and last_close:
        out["atr_pct"] = round(atr / last_close * 100.0, 6)
    else:
        out["atr_pct"] = None

    # ── EMA stack ───────────────────────────────────────────────────────────
    ema_df = compute_ema(df)
    out["ema_21"] = _last_value(ema_df, "ema_21")
    out["ema_50"] = _last_value(ema_df, "ema_50")
    out["ema_200"] = _last_value(ema_df, "ema_200")

    # ── Volume ratio (last bar / 20-bar SMA) ────────────────────────────────
    if "volume" in df.columns and len(df) >= 20:
        recent_vol = df["volume"].iloc[-20:].astype(float)
        avg = float(recent_vol.mean())
        last_vol = float(df["volume"].iloc[-1])
        out["volume_ratio"] = round(last_vol / avg, 6) if avg else None
    else:
        out["volume_ratio"] = None

    # ── OBV ─────────────────────────────────────────────────────────────────
    obv_df = compute_obv(df)
    out["obv"] = _last_value(obv_df, "obv")

    return out
