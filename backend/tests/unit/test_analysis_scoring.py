"""
Unit tests for analysis/scoring.py — normalize_oscillator, apply_decay,
aggregate_signals, build_composite.
"""

from __future__ import annotations

import pytest

from app.analysis.scoring import (
    CATEGORY_MAP,
    CATEGORY_WEIGHTS,
    aggregate_signals,
    apply_decay,
    build_composite,
    normalize_oscillator,
)


@pytest.mark.unit
class TestNormalizeOscillator:
    def test_at_extreme_low_returns_plus_one(self) -> None:
        assert normalize_oscillator(10.0, 20.0, 30.0, 70.0, 80.0) == pytest.approx(1.0)

    def test_at_extreme_high_returns_minus_one(self) -> None:
        assert normalize_oscillator(90.0, 20.0, 30.0, 70.0, 80.0) == pytest.approx(-1.0)

    def test_at_low_bullish_boundary(self) -> None:
        result = normalize_oscillator(20.0, 20.0, 30.0, 70.0, 80.0)
        assert result == pytest.approx(1.0)

    def test_at_high_bearish_boundary(self) -> None:
        result = normalize_oscillator(80.0, 20.0, 30.0, 70.0, 80.0)
        assert result == pytest.approx(-1.0)

    def test_midpoint_neutral(self) -> None:
        result = normalize_oscillator(50.0, 20.0, 30.0, 70.0, 80.0)
        assert abs(result) <= 0.1, f"Midpoint should be near 0, got {result}"

    def test_between_low_bullish_and_low_threshold(self) -> None:
        # value=25 is midpoint between 20 and 30
        result = normalize_oscillator(25.0, 20.0, 30.0, 70.0, 80.0)
        assert 0.3 < result < 1.0

    def test_between_high_threshold_and_high_bearish(self) -> None:
        # value=75 is midpoint between 70 and 80
        result = normalize_oscillator(75.0, 20.0, 30.0, 70.0, 80.0)
        assert -1.0 < result < -0.3


@pytest.mark.unit
class TestApplyDecay:
    def test_zero_bars_since_event(self) -> None:
        assert apply_decay(1.0, 0, 20) == pytest.approx(1.0)

    def test_decay_bars_elapsed_returns_zero(self) -> None:
        assert apply_decay(1.0, 20, 20) == pytest.approx(0.0)

    def test_past_decay_returns_zero(self) -> None:
        assert apply_decay(1.0, 25, 20) == pytest.approx(0.0)

    def test_half_decay(self) -> None:
        result = apply_decay(1.0, 10, 20)
        assert result == pytest.approx(0.5)

    def test_negative_value_decays(self) -> None:
        result = apply_decay(-1.0, 5, 20)
        assert result == pytest.approx(-0.75)

    def test_zero_decay_bars(self) -> None:
        assert apply_decay(1.0, 0, 0) == pytest.approx(0.0)

    def test_preserves_sign(self) -> None:
        assert apply_decay(-0.7, 0, 10) == pytest.approx(-0.7)


@pytest.mark.unit
class TestAggregateSignals:
    def test_missing_indicators_default_to_zero(self) -> None:
        # Empty signals → all categories should be 0.0
        cats = aggregate_signals({})
        for key in CATEGORY_MAP:
            assert cats[key] == pytest.approx(0.0)

    def test_all_categories_present(self) -> None:
        cats = aggregate_signals({})
        assert set(cats.keys()) == set(CATEGORY_MAP.keys())

    def test_single_indicator_averages_correctly(self) -> None:
        # trend has: ema_stack, adx_dmi, supertrend
        # If only ema_stack = 0.9 (others absent/failed), trend = 0.9 / 1 = 0.9
        cats = aggregate_signals({"ema_stack": 0.9})
        assert cats["trend"] == pytest.approx(0.9)

    def test_missing_indicators_excluded_from_average(self) -> None:
        # Two of three trend indicators present — denominator is 2, not 3
        cats = aggregate_signals({"ema_stack": 0.9, "adx_dmi": 0.3})
        assert cats["trend"] == pytest.approx((0.9 + 0.3) / 2)

    def test_full_signal_dict(self) -> None:
        signals = {ind: 1.0 for inds in CATEGORY_MAP.values() for ind in inds}
        cats = aggregate_signals(signals)
        for key in CATEGORY_MAP:
            assert cats[key] == pytest.approx(1.0)

    def test_mixed_signals(self) -> None:
        signals = {"ema_stack": 1.0, "adx_dmi": -1.0, "supertrend": 0.0}
        cats = aggregate_signals(signals)
        assert cats["trend"] == pytest.approx(0.0)


@pytest.mark.unit
class TestBuildComposite:
    def test_all_bullish_returns_positive(self) -> None:
        signals = {ind: 1.0 for inds in CATEGORY_MAP.values() for ind in inds}
        cats, comp = build_composite(signals)
        assert comp == pytest.approx(1.0)

    def test_all_bearish_returns_negative(self) -> None:
        signals = {ind: -1.0 for inds in CATEGORY_MAP.values() for ind in inds}
        cats, comp = build_composite(signals)
        assert comp == pytest.approx(-1.0)

    def test_neutral_returns_zero(self) -> None:
        cats, comp = build_composite({})
        assert comp == pytest.approx(0.0)

    def test_consistent_with_services_scoring(self) -> None:
        from app.services.scoring import composite_score

        signals = {"ema_stack": 0.8, "rsi": 0.6, "obv": 0.4}
        cats, comp = build_composite(signals)
        # Recompute manually via services.scoring
        expected = composite_score(cats, CATEGORY_WEIGHTS)
        assert comp == pytest.approx(expected)
