"""
Unit tests for scanner profiles.
"""

from __future__ import annotations

import pytest

from app.analysis.profiles import (
    HarmonicSetup,
    MeanReversion,
    MomentumBreakout,
    PROFILES,
    TrendFollowing,
    evaluate_profiles,
)


def _all_bullish() -> tuple[dict[str, float], dict[str, float], float]:
    """Return a maximally bullish signals, category_scores, composite triple."""
    signals = {
        "ema_stack": 1.0,
        "adx_dmi": 1.0,
        "supertrend": 1.0,
        "rsi": 1.0,
        "macd": 1.0,
        "stochastic": 1.0,
        "obv": 1.0,
        "vwap": 1.0,
        "cmf": 1.0,
        "bb_pct_b": 1.0,
        "ttm_squeeze": 1.0,
        "atr": 0.0,
        "fibonacci": 1.0,
        "pivot_points": 1.0,
        "rsi_divergence": 1.0,
        "macd_divergence": 1.0,
        "candlestick": 1.0,
    }
    cats = {
        "trend": 1.0,
        "momentum": 1.0,
        "volume": 1.0,
        "volatility": 1.0,
        "support_resistance": 1.0,
        "divergence": 1.0,
        "pattern": 1.0,
    }
    return signals, cats, 1.0


@pytest.mark.unit
class TestMomentumBreakoutProfile:
    def test_matches_when_all_conditions_met(self) -> None:
        signals, cats, comp = _all_bullish()
        signals["ttm_squeeze"] = 1.0  # fired
        cats["trend"] = 0.5
        cats["momentum"] = 0.5
        cats["volume"] = 0.5
        p = MomentumBreakout()
        result = p.check(signals, cats, comp)
        assert result.matches is True

    def test_fails_when_ttm_squeeze_not_fired(self) -> None:
        signals, cats, comp = _all_bullish()
        signals["ttm_squeeze"] = 0.0  # not fired
        p = MomentumBreakout()
        result = p.check(signals, cats, comp)
        assert result.matches is False
        assert result.conditions_met["ttm_squeeze_fired"] is False

    def test_fails_when_score_below_threshold(self) -> None:
        signals, cats, _ = _all_bullish()
        signals["ttm_squeeze"] = 1.0
        p = MomentumBreakout()
        result = p.check(signals, cats, 0.0)  # composite = 0 < threshold 0.4
        assert result.matches is False

    def test_conditions_dict_returned(self) -> None:
        signals, cats, comp = _all_bullish()
        p = MomentumBreakout()
        result = p.check(signals, cats, comp)
        assert "trend_bullish" in result.conditions_met
        assert "momentum_positive" in result.conditions_met


@pytest.mark.unit
class TestMeanReversionProfile:
    def test_matches_when_all_conditions_met(self) -> None:
        signals, cats, _ = _all_bullish()
        signals["rsi"] = 0.8  # oversold
        cats["support_resistance"] = 0.3
        cats["divergence"] = 0.2
        p = MeanReversion()
        result = p.check(signals, cats, 0.5)
        assert result.matches is True

    def test_fails_when_no_divergence(self) -> None:
        signals, cats, comp = _all_bullish()
        cats["divergence"] = -0.1  # negative divergence
        p = MeanReversion()
        result = p.check(signals, cats, comp)
        assert result.matches is False
        assert result.conditions_met["bullish_divergence"] is False

    def test_fails_when_not_oversold(self) -> None:
        signals, cats, comp = _all_bullish()
        signals["rsi"] = -0.5  # not oversold
        p = MeanReversion()
        result = p.check(signals, cats, comp)
        assert result.matches is False
        assert result.conditions_met["oversold"] is False


@pytest.mark.unit
class TestTrendFollowingProfile:
    def test_matches_when_all_conditions_met(self) -> None:
        signals, cats, _ = _all_bullish()
        signals["ema_stack"] = 1.0
        signals["adx_dmi"] = 0.5
        signals["supertrend"] = 1.0
        p = TrendFollowing()
        result = p.check(signals, cats, 0.5)
        assert result.matches is True

    def test_fails_when_supertrend_bearish(self) -> None:
        signals, cats, comp = _all_bullish()
        signals["supertrend"] = -1.0
        p = TrendFollowing()
        result = p.check(signals, cats, comp)
        assert result.matches is False
        assert result.conditions_met["supertrend_bullish"] is False

    def test_fails_when_ema_stack_low(self) -> None:
        signals, cats, comp = _all_bullish()
        signals["ema_stack"] = -0.33  # price below 2 EMAs
        p = TrendFollowing()
        result = p.check(signals, cats, comp)
        assert result.matches is False

    def test_fails_when_adx_too_low(self) -> None:
        signals, cats, comp = _all_bullish()
        signals["adx_dmi"] = 0.1  # weak trend
        p = TrendFollowing()
        result = p.check(signals, cats, comp)
        assert result.matches is False


@pytest.mark.unit
class TestHarmonicSetupProfile:
    def test_always_returns_false(self) -> None:
        signals, cats, comp = _all_bullish()
        p = HarmonicSetup()
        result = p.check(signals, cats, comp)
        assert result.matches is False

    def test_false_even_with_perfect_score(self) -> None:
        p = HarmonicSetup()
        result = p.check({"anything": 1.0}, {"trend": 1.0}, 1.0)
        assert result.matches is False


@pytest.mark.unit
class TestEvaluateProfiles:
    def test_returns_list(self) -> None:
        signals, cats, comp = _all_bullish()
        result = evaluate_profiles(signals, cats, comp)
        assert isinstance(result, list)

    def test_harmonic_never_in_results(self) -> None:
        signals, cats, comp = _all_bullish()
        result = evaluate_profiles(signals, cats, comp)
        assert "HarmonicSetup" not in result

    def test_all_profiles_registered(self) -> None:
        assert "MomentumBreakout" in PROFILES
        assert "MeanReversion" in PROFILES
        assert "TrendFollowing" in PROFILES
        assert "HarmonicSetup" in PROFILES
