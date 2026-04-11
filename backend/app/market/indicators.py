# backend/app/market/indicators.py
"""Broad market indicator computation — breadth, momentum, macro, sentiment."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _rsi(series: pd.Series, period: int = 14) -> float:
    """Compute RSI for the last bar. Returns 50.0 if insufficient data."""
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if np.isfinite(val) else 50.0


def compute_breadth(spx_close: pd.Series, rsp_close: pd.Series) -> dict[str, Any]:
    """Compute SPX/RSP breadth ratio and signal."""
    ratio = spx_close / rsp_close
    ratio_ma20 = ratio.rolling(20).mean()
    ratio_ma50 = ratio.rolling(50).mean()

    if len(ratio) >= 20:
        recent_change = float(ratio.iloc[-1] - ratio.iloc[-20])
        if recent_change < -0.01:
            signal = "broad"
        elif recent_change > 0.01:
            signal = "narrow"
        else:
            signal = "neutral"
    else:
        signal = "neutral"

    return {
        "ratio": ratio.tolist(),
        "ratio_ma20": ratio_ma20.tolist(),
        "ratio_ma50": ratio_ma50.tolist(),
        "current_ratio": float(ratio.iloc[-1]) if len(ratio) > 0 else None,
        "signal": signal,
        "dates": [d.isoformat() for d in ratio.index],
    }


def compute_momentum(
    spx_close: pd.Series, qqq_close: pd.Series, vix_close: pd.Series
) -> dict[str, Any]:
    """Compute SPX/QQQ RSI, VIX level and trend."""
    spx_rsi = _rsi(spx_close)
    qqq_rsi = _rsi(qqq_close)

    vix_last = float(vix_close.iloc[-1]) if len(vix_close) > 0 else 20.0

    if vix_last < 15:
        vix_label = "complacent"
    elif vix_last <= 25:
        vix_label = "normal"
    else:
        vix_label = "elevated"

    vix_20d_change = 0.0
    if len(vix_close) >= 20:
        vix_20d_change = float(vix_close.iloc[-1] - vix_close.iloc[-20])

    if spx_rsi > 70:
        momentum_label = "strong"
    elif spx_rsi > 50:
        momentum_label = "moderate"
    elif spx_rsi > 30:
        momentum_label = "weak"
    else:
        momentum_label = "oversold"

    return {
        "spx_rsi": round(spx_rsi, 1),
        "qqq_rsi": round(qqq_rsi, 1),
        "vix_last": round(vix_last, 2),
        "vix_level_label": vix_label,
        "vix_20d_change": round(vix_20d_change, 2),
        "momentum_label": momentum_label,
    }


def compute_macro(
    dgs10_df: pd.DataFrame,
    dgs2_df: pd.DataFrame,
    m2_df: pd.DataFrame,
    dxy_close: pd.Series,
) -> dict[str, Any]:
    """Compute yield curve spread, DXY RSI, M2 YoY change."""
    yield_spread: float | None = None
    yield_label = "unavailable"
    spread_30d_change: float | None = None

    if len(dgs10_df) > 0 and len(dgs2_df) > 0:
        latest_10y = dgs10_df.iloc[-1]["value"]
        latest_2y = dgs2_df.iloc[-1]["value"]
        if latest_10y is not None and latest_2y is not None:
            yield_spread = round(float(latest_10y) - float(latest_2y), 4)
            yield_label = "normal" if yield_spread >= 0 else "inverted"

            if len(dgs10_df) >= 30 and len(dgs2_df) >= 30:
                old_10y = dgs10_df.iloc[-30]["value"]
                old_2y = dgs2_df.iloc[-30]["value"]
                if old_10y is not None and old_2y is not None:
                    old_spread = float(old_10y) - float(old_2y)
                    spread_30d_change = round(yield_spread - old_spread, 4)

    dxy_rsi: float | None = None
    if len(dxy_close) > 14:
        dxy_rsi = round(_rsi(dxy_close), 1)

    m2_yoy: float | None = None
    if len(m2_df) >= 12:
        latest_m2 = m2_df.iloc[-1]["value"]
        year_ago_m2 = m2_df.iloc[-12]["value"]
        if latest_m2 is not None and year_ago_m2 is not None and float(year_ago_m2) > 0:
            m2_yoy = round((float(latest_m2) / float(year_ago_m2) - 1) * 100, 2)

    if yield_label == "unavailable":
        macro_label = "neutral"
    elif yield_label == "inverted":
        macro_label = "headwind"
    elif m2_yoy is not None and m2_yoy < 0:
        macro_label = "headwind"
    else:
        macro_label = "supportive"

    return {
        "yield_spread": yield_spread,
        "yield_curve_label": yield_label,
        "spread_30d_change": spread_30d_change,
        "dxy_rsi": dxy_rsi,
        "m2_yoy_pct": m2_yoy,
        "macro_label": macro_label,
    }


def compute_sentiment(aaii_readings: list[dict], naaim_readings: list[dict]) -> dict[str, Any]:
    """Compute AAII bull-bear spread stats and NAAIM exposure."""
    aaii_latest: float | None = None
    aaii_4wk_ma: float | None = None
    sentiment_label = "neutral"

    if aaii_readings:
        aaii_latest = aaii_readings[-1]["spread"]
        if len(aaii_readings) >= 4:
            last_4 = [r["spread"] for r in aaii_readings[-4:]]
            aaii_4wk_ma = round(sum(last_4) / 4, 2)

        if aaii_latest > 20:
            sentiment_label = "euphoric"
        elif aaii_latest > 10:
            sentiment_label = "complacent"
        elif aaii_latest < -20:
            sentiment_label = "fearful"
        elif aaii_latest < -10:
            sentiment_label = "fearful"

    naaim_latest: float | None = None
    if naaim_readings:
        naaim_latest = naaim_readings[-1].get("exposure")

    return {
        "aaii_latest_spread": aaii_latest,
        "aaii_4wk_ma": aaii_4wk_ma,
        "naaim_latest": naaim_latest,
        "sentiment_label": sentiment_label,
    }
