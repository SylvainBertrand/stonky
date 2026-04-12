"""LLM synthesis agent — generates structured trade setup analysis from aggregated signals.

Consumes AggregatedSignals, sends prompt to LLM provider, parses structured JSON response,
returns SynthesisResult. Designed for nightly batch processing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.analysis.signal_aggregator import AggregatedSignals
from app.llm.provider import LLMProvider

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a technical analysis assistant for a personal stock scanner.
Your job is to synthesize quantitative signals into a concise, actionable trade setup description.

Rules:
- Be specific and factual. Only reference signals that are actually present in the data.
- Do not invent signals or add generic filler ("the market is uncertain...").
- If signals conflict, say so explicitly. Do not paper over disagreements.
- Output must be in the exact JSON format specified. No prose outside the JSON.
- Confidence levels: "high" (strong multi-signal confluence), "medium" (mixed signals, \
some alignment), "low" (conflicting or weak signals).\
"""


@dataclass
class SynthesisResult:
    symbol: str
    generated_at: str
    setup_type: str
    bias: str  # "bullish" | "bearish" | "neutral"
    confidence: str  # "high" | "medium" | "low"
    summary: str
    signal_confluence: str
    signal_conflicts: str
    entry: float | None
    stop: float | None
    target: float | None
    risk_reward: float | None
    key_risk: str
    parse_error: bool = False
    raw_response: str = ""


async def synthesize(
    signals: AggregatedSignals,
    provider: LLMProvider,
) -> SynthesisResult:
    """Run LLM synthesis on aggregated signals. Never raises — returns error result on failure."""
    system_prompt = SYSTEM_PROMPT
    user_prompt = build_user_prompt(signals)

    try:
        raw = await provider.complete(system_prompt, user_prompt, max_tokens=800)
    except Exception as exc:
        log.error("LLM completion failed for %s: %s", signals.symbol, exc)
        return _error_result(signals.symbol, str(exc))

    return parse_response(raw, signals)


def build_user_prompt(signals: AggregatedSignals) -> str:
    """Build the user prompt from aggregated signals."""
    indicators = signals.indicators

    # Format chart patterns
    if signals.chart_patterns:
        patterns_summary = ", ".join(
            f"{p['name']} ({p['confidence']:.0%} confidence, {p['direction']})"
            for p in signals.chart_patterns
        )
    else:
        patterns_summary = "None detected"

    # Format EW section
    ew_section = ""
    if signals.ew_summary:
        ew_section = f"""
## Elliott Wave
{signals.ew_summary}"""
        if signals.ew_invalidation:
            ew_section += f"\nInvalidation: ${signals.ew_invalidation:.2f}"

    # Format forecast section
    forecast_section = "Not available"
    if signals.forecast_direction and signals.forecast_confidence is not None:
        forecast_section = (
            f"Direction: {signals.forecast_direction} "
            f"({signals.forecast_confidence:.0%} confidence)"
        )
        if signals.forecast_expected_move_pct is not None:
            sign = "+" if signals.forecast_expected_move_pct >= 0 else ""
            forecast_section += f"\nExpected move: {sign}{signals.forecast_expected_move_pct:.1f}%"
        if signals.forecast_range_low is not None and signals.forecast_range_high is not None:
            forecast_section += (
                f"  |  Range: ${signals.forecast_range_low:.2f}–${signals.forecast_range_high:.2f}"
            )

    # Format category scores
    cs = signals.category_scores
    profiles = ", ".join(signals.active_profile_matches) or "None"

    # Key indicator values
    rsi = indicators.get("rsi", 0.0)
    macd_hist = indicators.get("macd", 0.0)
    adx = indicators.get("adx_dmi", 0.0)
    stoch = indicators.get("stochastic", 0.0)
    ema_stack = indicators.get("ema_stack", 0.0)
    supertrend = "bullish" if indicators.get("supertrend", 0.0) > 0 else "bearish"
    squeeze = indicators.get("ttm_squeeze", 0.0)
    squeeze_status = "fired" if squeeze > 0.3 else "off" if squeeze < -0.3 else "building"

    # Risk levels
    entry_str = f"${signals.entry_zone:.2f}" if signals.entry_zone else "N/A"
    stop_str = f"${signals.stop_level:.2f}" if signals.stop_level else "N/A"
    target_str = f"${signals.target_level:.2f}" if signals.target_level else "N/A"
    rr_str = f"{signals.risk_reward_ratio:.1f}x" if signals.risk_reward_ratio else "N/A"

    return f"""\
Analyze the following signals for {signals.symbol} and produce a trade setup summary.

## Composite Score
{signals.composite_score:.2f} / 1.0  |  Active profiles: {profiles}

## Category Scores
Trend: {cs.get("trend", 0):.2f}  |  Momentum: {cs.get("momentum", 0):.2f}  |  \
Volume: {cs.get("volume", 0):.2f}
Volatility: {cs.get("volatility", 0):.2f}  |  S/R: {cs.get("support_resistance", 0):.2f}  |  \
Divergence: {cs.get("divergence", 0):.2f}

## Key Indicators
RSI signal: {rsi:+.2f}  |  MACD signal: {macd_hist:+.2f}  |  ADX signal: {adx:+.2f}  |  \
Stoch signal: {stoch:+.2f}
EMA stack: {ema_stack:+.2f} (price {signals.price_vs_ema21:+.1f}% vs EMA21, \
{signals.price_vs_ema200:+.1f}% vs EMA200)
Supertrend: {supertrend}  |  TTM Squeeze: {squeeze_status}

## Support/Resistance & Risk Levels
Entry zone: {entry_str}  |  Stop: {stop_str}  |  Target: {target_str}
Risk/Reward: {rr_str}  |  ATR: {signals.atr_pct:.1f}% of price

## Chart Patterns (YOLOv8)
{patterns_summary}

## Chronos-2 Forecast (20-day)
{forecast_section}
{ew_section}

## Instructions
Produce a JSON object with exactly these fields:
{{
  "setup_type": "...",
  "bias": "bullish|bearish|neutral",
  "confidence": "high|medium|low",
  "summary": "...",
  "signal_confluence": "...",
  "signal_conflicts": "...",
  "entry": null,
  "stop": null,
  "target": null,
  "risk_reward": null,
  "key_risk": "..."
}}

For entry/stop/target, use the values from Support/Resistance if available, \
or suggest your own based on the signals. Use null if uncertain.
"""


def parse_response(raw: str, signals: AggregatedSignals) -> SynthesisResult:
    """Extract JSON from LLM response. Robust to markdown fences and leading/trailing prose.

    Falls back to error result if parsing fails — never raises.
    """
    now = datetime.now(UTC).isoformat()

    # Try to extract JSON from markdown code fences
    json_str = _extract_json(raw)
    if json_str is None:
        log.warning("Failed to extract JSON from LLM response for %s", signals.symbol)
        return _error_result(signals.symbol, raw)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        log.warning("JSON parse failed for %s: %s", signals.symbol, exc)
        return _error_result(signals.symbol, raw)

    return SynthesisResult(
        symbol=signals.symbol,
        generated_at=now,
        setup_type=str(data.get("setup_type", "Unknown")),
        bias=_validate_enum(data.get("bias", "neutral"), ["bullish", "bearish", "neutral"]),
        confidence=_validate_enum(data.get("confidence", "low"), ["high", "medium", "low"]),
        summary=str(data.get("summary", "")),
        signal_confluence=str(data.get("signal_confluence", "")),
        signal_conflicts=str(data.get("signal_conflicts", "None")),
        entry=_safe_float(data.get("entry")),
        stop=_safe_float(data.get("stop")),
        target=_safe_float(data.get("target")),
        risk_reward=_safe_float(data.get("risk_reward")),
        key_risk=str(data.get("key_risk", "")),
        parse_error=False,
        raw_response=raw,
    )


def _extract_json(raw: str) -> str | None:
    """Extract JSON from response, handling markdown fences and surrounding prose."""
    if not raw or not raw.strip():
        return None

    # Try markdown code fence first: ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # Try raw JSON: find first { and last }
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return raw[first_brace : last_brace + 1]

    return None


def _validate_enum(value: str, allowed: list[str]) -> str:
    """Return value if in allowed list, else first allowed value."""
    v = str(value).lower().strip()
    return v if v in allowed else allowed[0]


def _safe_float(value: object) -> float | None:
    """Convert to float, returning None for None/invalid values."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]  # value: object, float() accepts it at runtime
    except (ValueError, TypeError):
        return None


def _error_result(symbol: str, raw_response: str) -> SynthesisResult:
    """Create a fallback result when LLM response can't be parsed."""
    return SynthesisResult(
        symbol=symbol,
        generated_at=datetime.now(UTC).isoformat(),
        setup_type="Parse Error",
        bias="neutral",
        confidence="low",
        summary="Analysis generation failed — will retry on next scheduled run.",
        signal_confluence="",
        signal_conflicts="",
        entry=None,
        stop=None,
        target=None,
        risk_reward=None,
        key_risk="LLM response could not be parsed.",
        parse_error=True,
        raw_response=raw_response[:2000],
    )
