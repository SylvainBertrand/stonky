# backend/app/market/regime.py
"""Market regime classification from indicator signals."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class MarketRegime:
    as_of_date: date | None = None
    regime: str = "choppy"
    breadth: str = "neutral"
    momentum: str = "moderate"
    sentiment: str = "neutral"
    macro: str = "neutral"
    summary: str = ""
    scanner_implication: str = ""


_IMPLICATIONS = {
    "bull_trending": "Favorable for momentum and trend-following setups",
    "bull_extended": "Consider tightening stops, extended conditions",
    "choppy": "Favor mean reversion, reduce position sizes",
    "bear_warning": "Defensive positioning, favor cash and hedges",
    "bear": "Reduce exposure, look for oversold bounces only",
}

_SUMMARIES = {
    "bull_trending": "Market in a healthy uptrend with broad participation.",
    "bull_extended": "Market trending higher but showing signs of overextension.",
    "choppy": "Mixed signals — no clear trend direction.",
    "bear_warning": "Deteriorating conditions, caution warranted.",
    "bear": "Market in a downtrend with elevated fear.",
}


def classify_regime(
    spx_above_200ema: bool,
    spx_rsi: float,
    breadth: str,
    vix: float,
    yield_inverted_months: int | None,
    aaii_spread: float | None,
    naaim_exposure: float | None,
) -> MarketRegime:
    """Classify market regime from indicator readings."""
    if spx_rsi > 70:
        momentum = "strong"
    elif spx_rsi > 50:
        momentum = "moderate"
    elif spx_rsi > 30:
        momentum = "weak"
    else:
        momentum = "oversold"

    sentiment = "neutral"
    if aaii_spread is not None:
        if aaii_spread > 20:
            sentiment = "euphoric"
        elif aaii_spread > 10:
            sentiment = "complacent"
        elif aaii_spread < -20:
            sentiment = "fearful"

    macro = "neutral"
    if yield_inverted_months is not None and yield_inverted_months > 3:
        macro = "headwind"
    elif yield_inverted_months is not None and yield_inverted_months == 0:
        macro = "supportive"

    if not spx_above_200ema and spx_rsi < 45 and vix > 25:
        naaim_check = naaim_exposure is None or naaim_exposure < 50
        if naaim_check:
            regime = "bear"
        else:
            regime = "bear_warning"
    elif not spx_above_200ema:
        regime = "bear_warning"
    elif vix > 20 and breadth == "neutral":
        regime = "choppy"
    elif spx_rsi > 70 and breadth == "narrow":
        regime = "bull_extended"
    elif spx_above_200ema and 50 <= spx_rsi <= 70 and breadth in ("broad", "neutral"):
        regime = "bull_trending"
    else:
        regime = "choppy"

    return MarketRegime(
        regime=regime,
        breadth=breadth,
        momentum=momentum,
        sentiment=sentiment,
        macro=macro,
        summary=_SUMMARIES.get(regime, ""),
        scanner_implication=_IMPLICATIONS.get(regime, ""),
    )
