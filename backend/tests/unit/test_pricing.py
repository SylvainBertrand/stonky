"""Unit tests for agents_common/pricing.py (TC-011)."""

from __future__ import annotations

import pytest

from app.agents_common.pricing import MODEL_RATES, estimate_cost_usd


@pytest.mark.unit
class TestEstimateCostUsd:
    def test_sonnet_zero_tokens(self) -> None:
        assert estimate_cost_usd(model="claude-sonnet-4-6", input_tokens=0, output_tokens=0) == 0.0

    def test_sonnet_1m_input_only(self) -> None:
        # 1M input tokens at $3/M = $3.00
        cost = estimate_cost_usd(model="claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(3.0, rel=1e-6)

    def test_sonnet_1m_output_only(self) -> None:
        # 1M output tokens at $15/M = $15.00
        cost = estimate_cost_usd(model="claude-sonnet-4-6", input_tokens=0, output_tokens=1_000_000)
        assert cost == pytest.approx(15.0, rel=1e-6)

    def test_sonnet_mixed_tokens(self) -> None:
        # 10k input at $3/M + 500 output at $15/M = 0.030 + 0.0075 = 0.0375
        cost = estimate_cost_usd(model="claude-sonnet-4-6", input_tokens=10_000, output_tokens=500)
        assert cost == pytest.approx(0.0375, rel=1e-5)

    def test_opus_rates(self) -> None:
        # 1M input at $15/M + 1M output at $75/M = $90
        cost = estimate_cost_usd(
            model="claude-opus-4-6", input_tokens=1_000_000, output_tokens=1_000_000
        )
        assert cost == pytest.approx(90.0, rel=1e-6)

    def test_haiku_rates(self) -> None:
        # 1M input at $1/M + 1M output at $5/M = $6
        cost = estimate_cost_usd(
            model="claude-haiku-4-5", input_tokens=1_000_000, output_tokens=1_000_000
        )
        assert cost == pytest.approx(6.0, rel=1e-6)

    def test_stonky_engine_is_zero(self) -> None:
        cost = estimate_cost_usd(model="stonky-engine", input_tokens=999_999, output_tokens=999_999)
        assert cost == 0.0

    def test_unknown_model_returns_zero(self) -> None:
        cost = estimate_cost_usd(
            model="gpt-99-turbo", input_tokens=1_000_000, output_tokens=1_000_000
        )
        assert cost == 0.0

    def test_result_rounded_to_6_decimals(self) -> None:
        # Ensure no excessive floating-point noise
        cost = estimate_cost_usd(model="claude-sonnet-4-6", input_tokens=1, output_tokens=1)
        assert cost == round(cost, 6)


@pytest.mark.unit
class TestModelRatesTable:
    def test_all_required_models_present(self) -> None:
        required = {"claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5", "stonky-engine"}
        assert required.issubset(MODEL_RATES.keys())

    def test_rates_are_non_negative(self) -> None:
        for model, rate in MODEL_RATES.items():
            assert rate.input_per_million >= 0, f"{model} has negative input rate"
            assert rate.output_per_million >= 0, f"{model} has negative output rate"
