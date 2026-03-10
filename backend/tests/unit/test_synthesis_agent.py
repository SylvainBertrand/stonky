"""Unit tests for LLM synthesis agent.

Tests cover:
- parse_response with well-formed JSON
- parse_response with JSON in markdown fences
- parse_response with malformed JSON
- parse_response with empty string
- build_user_prompt produces expected structure
- synthesize with mock LLM provider
"""
from __future__ import annotations

import json

import pytest

from app.analysis.signal_aggregator import AggregatedSignals
from app.analysis.synthesis_agent import (
    SynthesisResult,
    build_user_prompt,
    parse_response,
    synthesize,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_signals(**overrides: object) -> AggregatedSignals:
    """Create a minimal AggregatedSignals for testing."""
    defaults = dict(
        symbol="AAPL",
        timeframe="D1",
        as_of_date="2026-03-09",
        composite_score=0.65,
        category_scores={
            "trend": 0.7,
            "momentum": 0.5,
            "volume": 0.3,
            "volatility": 0.1,
            "support_resistance": 0.2,
            "divergence": 0.0,
            "pattern": 0.4,
        },
        active_profile_matches=["MomentumBreakout"],
        indicators={
            "rsi": 0.3,
            "macd": 0.5,
            "adx_dmi": 0.6,
            "stochastic": 0.2,
            "ema_stack": 0.7,
            "supertrend": 0.8,
            "ttm_squeeze": 0.4,
        },
        last_close=185.50,
        price_vs_ema21=2.5,
        price_vs_ema200=15.3,
        atr_pct=2.1,
        entry_zone=185.50,
        stop_level=181.00,
        target_level=195.00,
        risk_reward_ratio=2.1,
        chart_patterns=[
            {"name": "bull_flag", "confidence": 0.82, "direction": "bullish"},
        ],
        forecast_direction="bullish",
        forecast_expected_move_pct=4.2,
        forecast_confidence=0.75,
        forecast_range_low=178.50,
        forecast_range_high=195.20,
    )
    defaults.update(overrides)
    return AggregatedSignals(**defaults)  # type: ignore[arg-type]


_VALID_JSON_RESPONSE = json.dumps({
    "setup_type": "Momentum Breakout",
    "bias": "bullish",
    "confidence": "high",
    "summary": "AAPL shows strong momentum with bullish EMA stack.",
    "signal_confluence": "EMA stack, ADX, Supertrend all bullish.",
    "signal_conflicts": "None",
    "entry": 185.50,
    "stop": 181.00,
    "target": 195.00,
    "risk_reward": 2.1,
    "key_risk": "Break below $181 invalidates the setup.",
})


# ── parse_response tests ────────────────────────────────────────────────────


@pytest.mark.unit
class TestParseResponse:
    def test_well_formed_json(self) -> None:
        signals = _make_signals()
        result = parse_response(_VALID_JSON_RESPONSE, signals)

        assert result.symbol == "AAPL"
        assert result.setup_type == "Momentum Breakout"
        assert result.bias == "bullish"
        assert result.confidence == "high"
        assert result.summary == "AAPL shows strong momentum with bullish EMA stack."
        assert result.entry == pytest.approx(185.50)
        assert result.stop == pytest.approx(181.00)
        assert result.target == pytest.approx(195.00)
        assert result.risk_reward == pytest.approx(2.1)
        assert result.parse_error is False

    def test_json_in_markdown_fences(self) -> None:
        raw = f"Here is my analysis:\n\n```json\n{_VALID_JSON_RESPONSE}\n```\n\nHope this helps!"
        signals = _make_signals()
        result = parse_response(raw, signals)

        assert result.parse_error is False
        assert result.setup_type == "Momentum Breakout"
        assert result.bias == "bullish"

    def test_json_in_plain_fences(self) -> None:
        raw = f"```\n{_VALID_JSON_RESPONSE}\n```"
        signals = _make_signals()
        result = parse_response(raw, signals)

        assert result.parse_error is False
        assert result.setup_type == "Momentum Breakout"

    def test_json_with_leading_trailing_prose(self) -> None:
        raw = f"Based on the signals, here's my analysis:\n{_VALID_JSON_RESPONSE}\nThat's my take."
        signals = _make_signals()
        result = parse_response(raw, signals)

        assert result.parse_error is False
        assert result.setup_type == "Momentum Breakout"

    def test_malformed_json(self) -> None:
        raw = '{"setup_type": "Breakout", "bias": "bullish", INVALID}'
        signals = _make_signals()
        result = parse_response(raw, signals)

        assert result.parse_error is True
        assert result.setup_type == "Parse Error"
        assert result.bias == "neutral"

    def test_empty_string(self) -> None:
        signals = _make_signals()
        result = parse_response("", signals)

        assert result.parse_error is True
        assert result.setup_type == "Parse Error"

    def test_whitespace_only(self) -> None:
        signals = _make_signals()
        result = parse_response("   \n\n  ", signals)

        assert result.parse_error is True

    def test_missing_optional_fields(self) -> None:
        raw = json.dumps({
            "setup_type": "No Clear Setup",
            "bias": "neutral",
            "confidence": "low",
            "summary": "Mixed signals.",
            "signal_confluence": "None strong.",
            "signal_conflicts": "Everything conflicts.",
            "key_risk": "No clear direction.",
        })
        signals = _make_signals()
        result = parse_response(raw, signals)

        assert result.parse_error is False
        assert result.entry is None
        assert result.stop is None
        assert result.target is None
        assert result.risk_reward is None

    def test_invalid_bias_defaults(self) -> None:
        raw = json.dumps({
            "setup_type": "Test",
            "bias": "INVALID",
            "confidence": "WRONG",
            "summary": "Test.",
            "signal_confluence": "",
            "signal_conflicts": "",
            "key_risk": "Test.",
        })
        signals = _make_signals()
        result = parse_response(raw, signals)

        assert result.bias == "bullish"  # first allowed value
        assert result.confidence == "high"  # first allowed value


# ── build_user_prompt tests ──────────────────────────────────────────────────


@pytest.mark.unit
class TestBuildUserPrompt:
    def test_contains_symbol(self) -> None:
        signals = _make_signals()
        prompt = build_user_prompt(signals)
        assert "AAPL" in prompt

    def test_contains_composite_score(self) -> None:
        signals = _make_signals()
        prompt = build_user_prompt(signals)
        assert "0.65" in prompt

    def test_contains_category_scores(self) -> None:
        signals = _make_signals()
        prompt = build_user_prompt(signals)
        assert "Trend:" in prompt
        assert "Momentum:" in prompt
        assert "Volume:" in prompt

    def test_contains_chart_patterns(self) -> None:
        signals = _make_signals()
        prompt = build_user_prompt(signals)
        assert "bull_flag" in prompt
        assert "82%" in prompt

    def test_contains_forecast(self) -> None:
        signals = _make_signals()
        prompt = build_user_prompt(signals)
        assert "bullish" in prompt
        assert "+4.2%" in prompt

    def test_no_chart_patterns(self) -> None:
        signals = _make_signals(chart_patterns=[])
        prompt = build_user_prompt(signals)
        assert "None detected" in prompt

    def test_no_forecast(self) -> None:
        signals = _make_signals(
            forecast_direction=None,
            forecast_confidence=None,
            forecast_expected_move_pct=None,
        )
        prompt = build_user_prompt(signals)
        assert "Not available" in prompt

    def test_includes_ew_section(self) -> None:
        signals = _make_signals(ew_summary="Wave 3 of impulse (high confidence)")
        prompt = build_user_prompt(signals)
        assert "Elliott Wave" in prompt
        assert "Wave 3" in prompt

    def test_contains_json_instructions(self) -> None:
        signals = _make_signals()
        prompt = build_user_prompt(signals)
        assert '"setup_type"' in prompt
        assert '"bias"' in prompt
        assert '"confidence"' in prompt

    def test_contains_risk_levels(self) -> None:
        signals = _make_signals()
        prompt = build_user_prompt(signals)
        assert "$185.50" in prompt
        assert "$181.00" in prompt
        assert "$195.00" in prompt


# ── synthesize tests ─────────────────────────────────────────────────────────


class MockProvider:
    """Mock LLM provider that returns a hardcoded response."""

    def __init__(self, response: str = _VALID_JSON_RESPONSE):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        self.calls.append((system, user))
        return self.response


class FailingProvider:
    """Mock LLM provider that raises an exception."""

    async def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        raise RuntimeError("Connection refused")


@pytest.mark.unit
class TestSynthesize:
    @pytest.mark.asyncio
    async def test_successful_synthesis(self) -> None:
        signals = _make_signals()
        provider = MockProvider()
        result = await synthesize(signals, provider)

        assert result.symbol == "AAPL"
        assert result.setup_type == "Momentum Breakout"
        assert result.parse_error is False
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_provider_failure_returns_error_result(self) -> None:
        signals = _make_signals()
        provider = FailingProvider()
        result = await synthesize(signals, provider)

        assert result.parse_error is True
        assert result.setup_type == "Parse Error"
        assert "Connection refused" in result.raw_response

    @pytest.mark.asyncio
    async def test_malformed_response_returns_error_result(self) -> None:
        signals = _make_signals()
        provider = MockProvider(response="This is not JSON at all")
        result = await synthesize(signals, provider)

        assert result.parse_error is True
