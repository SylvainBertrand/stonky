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
    def _mr_signals(self) -> tuple[dict[str, float], dict[str, float]]:
        """Minimal signals satisfying MR conditions."""
        signals = {
            "rsi": 0.8,          # oversold (RSI < ~35)
            "stochastic": 0.5,   # %K < 25 oversold zone
            "rsi_divergence": 0.0,
            "bb_pct_b": 0.0,
        }
        cats = {
            "trend": 0.0,
            "momentum": 0.3,
            "volume": 0.2,
            "volatility": 0.0,
            "support_resistance": 0.4,
            "divergence": 0.0,
            "pattern": 0.0,
        }
        return signals, cats

    def test_matches_when_all_conditions_met(self) -> None:
        signals, cats = self._mr_signals()
        p = MeanReversion()
        result = p.check(signals, cats, 0.15)
        assert result.matches is True

    def test_fails_when_not_oversold_and_no_divergence(self) -> None:
        signals, cats = self._mr_signals()
        signals["rsi"] = -0.5         # overbought, not oversold
        signals["rsi_divergence"] = 0.0  # no divergence either
        p = MeanReversion()
        result = p.check(signals, cats, 0.15)
        assert result.matches is False
        assert result.conditions_met["oversold_or_divergence"] is False

    def test_passes_via_divergence_when_rsi_not_oversold(self) -> None:
        signals, cats = self._mr_signals()
        signals["rsi"] = -0.2          # mild overbought, not oversold zone
        signals["rsi_divergence"] = 0.5  # but bullish RSI divergence present
        p = MeanReversion()
        result = p.check(signals, cats, 0.15)
        # oversold_or_divergence → True via divergence
        assert result.conditions_met["oversold_or_divergence"] is True

    def test_fails_when_stochastic_not_oversold(self) -> None:
        signals, cats = self._mr_signals()
        signals["stochastic"] = -0.5  # overbought stochastic
        p = MeanReversion()
        result = p.check(signals, cats, 0.15)
        assert result.matches is False
        assert result.conditions_met["stochastic_oversold"] is False

    def test_fails_when_score_below_threshold(self) -> None:
        signals, cats = self._mr_signals()
        p = MeanReversion()
        # threshold is 0.1; composite = 0.05 → fails
        result = p.check(signals, cats, 0.05)
        assert result.matches is False


@pytest.mark.unit
class TestTrendFollowingProfile:
    def _tf_signals(self) -> tuple[dict[str, float], dict[str, float]]:
        """Signals for a healthy uptrend satisfying all TF conditions."""
        signals = {
            "ema_stack": 1.0,    # above all 3 EMAs
            "adx_dmi": 0.5,      # ADX > 25, DI+ > DI-
            "supertrend": 1.0,   # bullish
            "rsi": -0.1,         # RSI ~55 (in 40-65 healthy range)
            "obv": 0.4,          # OBV trending up
        }
        cats = {
            "trend": 0.8,
            "momentum": 0.4,
            "volume": 0.3,
            "volatility": 0.1,
            "support_resistance": 0.2,
            "divergence": 0.0,
            "pattern": 0.0,
        }
        return signals, cats

    def test_matches_when_all_conditions_met(self) -> None:
        signals, cats = self._tf_signals()
        p = TrendFollowing()
        result = p.check(signals, cats, 0.5)
        assert result.matches is True

    def test_fails_when_supertrend_bearish(self) -> None:
        signals, cats = self._tf_signals()
        signals["supertrend"] = -1.0
        p = TrendFollowing()
        result = p.check(signals, cats, 0.5)
        assert result.matches is False
        assert result.conditions_met["supertrend_bullish"] is False

    def test_fails_when_ema_stack_low(self) -> None:
        signals, cats = self._tf_signals()
        signals["ema_stack"] = -0.33  # price below 2 EMAs
        p = TrendFollowing()
        result = p.check(signals, cats, 0.5)
        assert result.matches is False

    def test_fails_when_adx_too_low(self) -> None:
        signals, cats = self._tf_signals()
        signals["adx_dmi"] = 0.1  # weak trend
        p = TrendFollowing()
        result = p.check(signals, cats, 0.5)
        assert result.matches is False

    def test_fails_when_rsi_too_high(self) -> None:
        signals, cats = self._tf_signals()
        signals["rsi"] = 0.8  # extreme oversold (RSI < 20) — not in healthy uptrend range
        p = TrendFollowing()
        result = p.check(signals, cats, 0.5)
        assert result.matches is False
        assert result.conditions_met["rsi_in_range"] is False

    def test_fails_when_obv_declining(self) -> None:
        signals, cats = self._tf_signals()
        signals["obv"] = -0.3  # OBV declining
        p = TrendFollowing()
        result = p.check(signals, cats, 0.5)
        assert result.matches is False
        assert result.conditions_met["obv_rising"] is False


@pytest.mark.unit
class TestHarmonicSetupProfile:
    def test_fails_without_harmonic_signals(self) -> None:
        # _all_bullish() doesn't include harmonic_pattern_detected → fails
        signals, cats, comp = _all_bullish()
        p = HarmonicSetup()
        result = p.check(signals, cats, comp)
        assert result.matches is False

    def test_matches_with_full_harmonic_signals(self) -> None:
        signals, cats, _ = _all_bullish()
        signals["harmonic_pattern_detected"] = 1.0  # detected
        signals["harmonic_ratio_quality"] = 0.85    # quality >= 0.75
        signals["rsi_divergence"] = 0.6             # divergence present
        p = HarmonicSetup()
        result = p.check(signals, cats, 0.3)
        assert result.matches is True
        assert result.conditions_met["harmonic_pattern_detected"] is True
        assert result.conditions_met["harmonic_quality"] is True
        assert result.conditions_met["rsi_or_macd_divergence"] is True

    def test_fails_when_quality_below_threshold(self) -> None:
        signals, cats, _ = _all_bullish()
        signals["harmonic_pattern_detected"] = 1.0
        signals["harmonic_ratio_quality"] = 0.6   # < 0.75
        signals["rsi_divergence"] = 0.6
        p = HarmonicSetup()
        result = p.check(signals, cats, 0.3)
        assert result.matches is False
        assert result.conditions_met["harmonic_quality"] is False


@pytest.mark.unit
class TestEvaluateProfiles:
    def test_returns_list(self) -> None:
        signals, cats, comp = _all_bullish()
        result = evaluate_profiles(signals, cats, comp)
        assert isinstance(result, list)

    def test_harmonic_absent_without_harmonic_signals(self) -> None:
        # _all_bullish() has no harmonic_pattern_detected → HarmonicSetup can't match
        signals, cats, comp = _all_bullish()
        result = evaluate_profiles(signals, cats, comp)
        assert "HarmonicSetup" not in result

    def test_all_profiles_registered(self) -> None:
        assert "MomentumBreakout" in PROFILES
        assert "MeanReversion" in PROFILES
        assert "TrendFollowing" in PROFILES
        assert "HarmonicSetup" in PROFILES
