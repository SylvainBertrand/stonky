"""
Unit tests for the scoring module — pure logic, no I/O.

Covers:
- RSI normalization to [-1, 1]
- Composite weighted score calculation
- Hard filter: min_categories_agreeing
"""

import pytest

from app.services.scoring import composite_score, normalize_rsi, passes_filter


@pytest.mark.unit
class TestNormalizeRsi:
    def test_oversold_rsi_is_bullish(self) -> None:
        score = normalize_rsi(28.5)
        assert score > 0, f"RSI 28.5 should map to positive (bullish) score, got {score}"

    def test_overbought_rsi_is_bearish(self) -> None:
        score = normalize_rsi(75.0)
        assert score < 0, f"RSI 75 should map to negative (bearish) score, got {score}"

    def test_neutral_rsi_is_zero(self) -> None:
        assert normalize_rsi(50.0) == pytest.approx(0.0)

    def test_extreme_oversold_clamps_to_positive_one(self) -> None:
        assert normalize_rsi(0.0) == pytest.approx(1.0)

    def test_extreme_overbought_clamps_to_negative_one(self) -> None:
        assert normalize_rsi(100.0) == pytest.approx(-1.0)

    def test_score_range(self) -> None:
        for rsi in range(0, 101, 5):
            score = normalize_rsi(float(rsi))
            assert -1.0 <= score <= 1.0, f"Score out of range for RSI {rsi}: {score}"


@pytest.mark.unit
class TestCompositeScore:
    def test_weighted_sum(self) -> None:
        category_scores = {"trend": 0.8, "momentum": -0.4}
        weights = {"trend": 0.30, "momentum": 0.20}
        result = composite_score(category_scores, weights)
        # (0.8 * 0.30 + (-0.4) * 0.20) / (0.30 + 0.20)
        expected = (0.8 * 0.30 + (-0.4) * 0.20) / (0.30 + 0.20)
        assert result == pytest.approx(expected, abs=1e-9)

    def test_all_categories(self) -> None:
        weights = {
            "trend": 0.30,
            "momentum": 0.20,
            "volume": 0.15,
            "volatility": 0.10,
            "support_resistance": 0.10,
            "divergence": 0.10,
            "pattern": 0.05,
        }
        # All equal scores → composite equals that score
        uniform_score = 0.5
        scores = {k: uniform_score for k in weights}
        result = composite_score(scores, weights)
        assert result == pytest.approx(uniform_score, abs=1e-9)

    def test_zero_weight_returns_zero(self) -> None:
        result = composite_score({"trend": 0.9}, {})
        assert result == 0.0

    def test_missing_category_weight_treated_as_zero(self) -> None:
        scores = {"trend": 0.8, "momentum": 0.6}
        # Only trend has weight; momentum contributes nothing
        result = composite_score(scores, {"trend": 1.0})
        assert result == pytest.approx(0.8, abs=1e-9)


@pytest.mark.unit
class TestPassesFilter:
    def test_exactly_meets_minimum(self) -> None:
        scores = {"trend": 0.5, "momentum": 0.3, "volume": 0.1}
        assert passes_filter(scores, min_categories_agreeing=3)

    def test_too_few_agreeing(self) -> None:
        scores = {"trend": 0.5, "momentum": -0.3, "volume": 0.1}
        # Only 2 positive, need 3
        assert not passes_filter(scores, min_categories_agreeing=3)

    def test_zero_minimum_always_passes(self) -> None:
        scores = {"trend": -0.9, "momentum": -0.5}
        assert passes_filter(scores, min_categories_agreeing=0)

    def test_all_negative_fails(self) -> None:
        scores = {"trend": -0.8, "momentum": -0.4, "volume": -0.2}
        assert not passes_filter(scores, min_categories_agreeing=1)

    def test_exactly_zero_score_does_not_count(self) -> None:
        scores = {"trend": 0.0, "momentum": 0.5}
        # 0.0 is not > 0, so only momentum agrees
        assert not passes_filter(scores, min_categories_agreeing=2)
