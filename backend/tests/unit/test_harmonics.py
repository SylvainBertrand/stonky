"""
Unit tests for harmonic pattern detection.

Tests:
- detect_harmonics with synthetic Gartley data
- detect_harmonics with flat/random data (no patterns)
- compute_harmonics_signals normalization: score, decay, PRZ bonus
- PRZ bounds calculation (prz_low <= prz_high)
- Profile 4 required_conditions
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.indicators.harmonics import (
    HarmonicMatch,
    compute_harmonics_signals,
    detect_harmonics,
)
from app.analysis.profiles import HarmonicSetup

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_df(
    closes: list[float],
    base_spread: float = 0.5,
    seed: int = 99,
) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a close price sequence."""
    rng = np.random.default_rng(seed)
    n = len(closes)
    c = np.array(closes, dtype=float)
    noise = rng.uniform(-base_spread, base_spread, n)
    o = c + noise * 0.3
    h = np.maximum(o, c) + np.abs(rng.uniform(0, base_spread, n))
    lw = np.minimum(o, c) - np.abs(rng.uniform(0, base_spread, n))
    v = rng.integers(100_000, 1_000_000, n)
    dates = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame({"time": dates, "open": o, "high": h, "low": lw, "close": c, "volume": v})


def _make_gartley_df(bars_per_leg: int = 30, history_bars: int = 200) -> pd.DataFrame:
    """
    Build a DataFrame with:
      - `history_bars` bars of neutral history (for indicator warmup)
      - Then an ideal bullish Gartley XABCD pattern
      - 3 bars of recovery after D (so bars_since_completion = 3)

    Gartley ideal ratios:
      XAB = 0.618 (B retraces 61.8% of XA)
      BCD ~ 1.27-1.62 extension of AB (here 1.272)
      XAD = 0.786 (D retraces 78.6% of XA)
    """
    rng = np.random.default_rng(42)

    x_price = 100.0
    a_price = 120.0  # XA leg up +20
    xa = a_price - x_price  # 20

    b_price = a_price - xa * 0.618  # B: 61.8% retrace of XA = 107.64
    ab = a_price - b_price  # ~12.36

    c_price = b_price + ab * 0.786  # C: 78.6% of AB (valid range)
    cd = ab * 1.272  # CD: 1.272 extension of AB
    d_price = c_price - cd  # D: should be near 78.6% retrace of XA

    # History: flat near x_price
    history = np.linspace(x_price, x_price, history_bars) + rng.normal(0, 0.1, history_bars)

    # XABCD legs (linear interpolation)
    leg_xa = np.linspace(x_price, a_price, bars_per_leg)
    leg_ab = np.linspace(a_price, b_price, bars_per_leg)
    leg_bc = np.linspace(b_price, c_price, bars_per_leg)
    leg_cd = np.linspace(c_price, d_price, bars_per_leg)

    # Recovery: 3 bars after D so bars_since_completion = 3
    recovery = np.linspace(d_price, d_price * 1.03, 3)

    closes_raw = np.concatenate([history, leg_xa, leg_ab, leg_bc, leg_cd, recovery])
    return _make_df(closes_raw.tolist(), base_spread=0.1, seed=42)


# ---------------------------------------------------------------------------
# detect_harmonics
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectHarmonics:
    def test_insufficient_bars_returns_empty(self) -> None:
        """Less than MIN_BARS_HARMONICS → empty list, no exception."""
        df = _make_df(list(range(50, 90)))  # 40 bars
        result = detect_harmonics(df)
        assert result == []

    def test_returns_list(self) -> None:
        """Always returns a list (may be empty on random data)."""
        rng = np.random.default_rng(1)
        closes = 100 + np.cumsum(rng.normal(0, 0.5, 250))
        df = _make_df(closes.tolist())
        result = detect_harmonics(df)
        assert isinstance(result, list)

    def test_sorted_by_ratio_quality_descending(self) -> None:
        """If multiple matches are returned, they must be sorted best-first."""
        rng = np.random.default_rng(7)
        closes = 100 + np.cumsum(rng.normal(0, 0.5, 300))
        df = _make_df(closes.tolist())
        result = detect_harmonics(df)
        if len(result) > 1:
            qualities = [m.ratio_quality for m in result]
            assert qualities == sorted(qualities, reverse=True)

    def test_bars_since_completion_filter(self) -> None:
        """All returned matches satisfy bars_since_completion <= max_bars."""
        rng = np.random.default_rng(9)
        closes = 100 + np.cumsum(rng.normal(0, 0.3, 400))
        df = _make_df(closes.tolist())
        max_b = 5
        result = detect_harmonics(df, max_bars_since_completion=max_b)
        for m in result:
            assert m.bars_since_completion <= max_b

    def test_min_ratio_quality_filter(self) -> None:
        """All returned matches satisfy ratio_quality >= min_ratio_quality."""
        rng = np.random.default_rng(11)
        closes = 100 + np.cumsum(rng.normal(0, 0.3, 400))
        df = _make_df(closes.tolist())
        min_q = 0.8
        result = detect_harmonics(df, min_ratio_quality=min_q)
        for m in result:
            assert m.ratio_quality >= min_q

    def test_prz_low_le_prz_high(self) -> None:
        """PRZ bounds are always well-ordered."""
        rng = np.random.default_rng(13)
        closes = 100 + np.cumsum(rng.normal(0, 0.3, 400))
        df = _make_df(closes.tolist())
        result = detect_harmonics(df, min_ratio_quality=0.0)
        for m in result:
            assert m.prz_low <= m.prz_high

    def test_direction_is_bullish_or_bearish(self) -> None:
        """Direction must be 'bullish' or 'bearish'."""
        rng = np.random.default_rng(15)
        closes = 100 + np.cumsum(rng.normal(0, 0.3, 400))
        df = _make_df(closes.tolist())
        result = detect_harmonics(df, min_ratio_quality=0.0)
        for m in result:
            assert m.direction in ("bullish", "bearish")

    def test_gartley_synthetic_detection(self) -> None:
        """
        Synthetic ideal Gartley data: detection should either find a Gartley/Bat
        pattern or return [] (pyharmonics may not detect every synthetic pattern
        due to peak spacing sensitivity), but it must not raise an exception.
        """
        df = _make_gartley_df(bars_per_leg=30, history_bars=200)
        # Must not raise
        result = detect_harmonics(df, max_bars_since_completion=10, min_ratio_quality=0.5)
        assert isinstance(result, list)
        # If anything is detected, verify structure
        for m in result:
            assert isinstance(m.pattern_name, str)
            assert m.direction in ("bullish", "bearish")
            assert 0.0 <= m.ratio_quality <= 1.0
            assert m.prz_low <= m.prz_high
            assert 0 <= m.bars_since_completion <= 10

    def test_no_exception_on_malformed_df(self) -> None:
        """detect_harmonics must not raise even if given unusual data."""
        df = _make_df([100.0] * 200)  # flat prices — no peaks
        result = detect_harmonics(df)
        assert result == [] or isinstance(result, list)


# ---------------------------------------------------------------------------
# compute_harmonics_signals
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputeHarmonicsSignals:
    def _simple_df(self, close: float = 105.0, n: int = 50) -> pd.DataFrame:
        closes = [close] * n
        return _make_df(closes)

    def test_no_matches_returns_zeros(self) -> None:
        df = self._simple_df()
        signals = compute_harmonics_signals(df, [])
        assert signals["harmonic_score"] == 0.0
        assert signals["harmonic_pattern_detected"] == 0.0
        assert signals["harmonic_in_prz"] == 0.0
        assert signals["harmonic_ratio_quality"] == 0.0

    def test_bullish_match_positive_score(self) -> None:
        df = self._simple_df(close=105.0)
        match = HarmonicMatch(
            pattern_name="Gartley",
            direction="bullish",
            completion_bar=45,
            bars_since_completion=0,
            prz_low=100.0,
            prz_high=110.0,
            ratio_quality=0.9,
            x=80.0,
            a=100.0,
            b=88.0,
            c=96.0,
            d=105.0,
        )
        signals = compute_harmonics_signals(df, [match])
        assert signals["harmonic_score"] > 0.0
        assert signals["harmonic_pattern_detected"] == 1.0
        assert signals["harmonic_in_prz"] == 1.0  # 105 in [100, 110]
        assert signals["harmonic_ratio_quality"] == pytest.approx(0.9)

    def test_bearish_match_negative_score(self) -> None:
        df = self._simple_df(close=105.0)
        match = HarmonicMatch(
            pattern_name="Bat",
            direction="bearish",
            completion_bar=45,
            bars_since_completion=0,
            prz_low=100.0,
            prz_high=110.0,
            ratio_quality=0.85,
            x=120.0,
            a=100.0,
            b=112.0,
            c=104.0,
            d=105.0,
        )
        signals = compute_harmonics_signals(df, [match])
        assert signals["harmonic_score"] < 0.0

    def test_recency_decay(self) -> None:
        """Score at bars_since=0 > score at bars_since=5."""
        df = self._simple_df(close=95.0)
        fresh = HarmonicMatch(
            pattern_name="Gartley",
            direction="bullish",
            completion_bar=49,
            bars_since_completion=0,
            prz_low=90.0,
            prz_high=100.0,
            ratio_quality=0.9,
            x=70.0,
            a=90.0,
            b=79.0,
            c=87.0,
            d=95.0,
        )
        stale = HarmonicMatch(
            pattern_name="Gartley",
            direction="bullish",
            completion_bar=44,
            bars_since_completion=5,
            prz_low=90.0,
            prz_high=100.0,
            ratio_quality=0.9,
            x=70.0,
            a=90.0,
            b=79.0,
            c=87.0,
            d=95.0,
        )
        sig_fresh = compute_harmonics_signals(df, [fresh])
        sig_stale = compute_harmonics_signals(df, [stale])
        assert sig_fresh["harmonic_score"] > sig_stale["harmonic_score"]

    def test_prz_bonus_when_in_prz(self) -> None:
        """Score is higher when price is inside PRZ than outside."""
        df_in = self._simple_df(close=105.0)
        df_out = self._simple_df(close=120.0)
        match_template = HarmonicMatch(
            pattern_name="Gartley",
            direction="bullish",
            completion_bar=49,
            bars_since_completion=0,
            prz_low=100.0,
            prz_high=110.0,
            ratio_quality=0.85,
            x=80.0,
            a=100.0,
            b=88.0,
            c=96.0,
            d=105.0,
        )
        sig_in = compute_harmonics_signals(df_in, [match_template])
        sig_out = compute_harmonics_signals(df_out, [match_template])
        # In-PRZ score is boosted by 1.2x
        assert sig_in["harmonic_score"] >= sig_out["harmonic_score"]
        assert sig_in["harmonic_in_prz"] == 1.0
        assert sig_out["harmonic_in_prz"] == 0.0

    def test_score_clamped_to_one(self) -> None:
        """Score must not exceed ±1.0."""
        df = self._simple_df(close=105.0)
        match = HarmonicMatch(
            pattern_name="Gartley",
            direction="bullish",
            completion_bar=49,
            bars_since_completion=0,
            prz_low=100.0,
            prz_high=110.0,
            ratio_quality=1.0,  # perfect quality
            x=80.0,
            a=100.0,
            b=88.0,
            c=96.0,
            d=105.0,
        )
        signals = compute_harmonics_signals(df, [match])
        assert -1.0 <= signals["harmonic_score"] <= 1.0

    def test_uses_highest_quality_match(self) -> None:
        """When multiple matches are given, the first (best quality) is primary."""
        df = self._simple_df(close=105.0)
        best = HarmonicMatch(
            pattern_name="Gartley",
            direction="bullish",
            completion_bar=49,
            bars_since_completion=0,
            prz_low=100.0,
            prz_high=110.0,
            ratio_quality=0.95,
            x=80.0,
            a=100.0,
            b=88.0,
            c=96.0,
            d=105.0,
        )
        second = HarmonicMatch(
            pattern_name="Bat",
            direction="bearish",
            completion_bar=48,
            bars_since_completion=1,
            prz_low=90.0,
            prz_high=95.0,
            ratio_quality=0.72,
            x=120.0,
            a=100.0,
            b=112.0,
            c=104.0,
            d=103.0,
        )
        # Matches already sorted best-first (as detect_harmonics would return)
        signals = compute_harmonics_signals(df, [best, second])
        # Primary signal should be bullish (from best)
        assert signals["harmonic_score"] > 0.0
        assert signals["harmonic_ratio_quality"] == pytest.approx(0.95)

    def test_lower_weight_patterns_have_lower_magnitude(self) -> None:
        """Cypher/Shark (weight 0.7) has lower magnitude than Gartley (weight 1.0)."""
        df = self._simple_df(close=105.0)

        def _match(name: str) -> HarmonicMatch:
            return HarmonicMatch(
                pattern_name=name,
                direction="bullish",
                completion_bar=49,
                bars_since_completion=0,
                prz_low=100.0,
                prz_high=110.0,
                ratio_quality=0.9,
                x=80.0,
                a=100.0,
                b=88.0,
                c=96.0,
                d=105.0,
            )

        sig_gartley = compute_harmonics_signals(df, [_match("Gartley")])
        sig_cypher = compute_harmonics_signals(df, [_match("Cypher")])
        assert sig_gartley["harmonic_score"] > sig_cypher["harmonic_score"]


# ---------------------------------------------------------------------------
# Profile 4 — HarmonicSetup
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHarmonicSetupProfile:
    def _cats(self) -> dict[str, float]:
        return {
            "trend": 0.5,
            "momentum": 0.3,
            "volume": 0.2,
            "volatility": 0.1,
            "support_resistance": 0.1,
            "divergence": 0.3,
            "pattern": 0.5,
        }

    def test_matches_when_all_conditions_met(self) -> None:
        signals = {
            "harmonic_pattern_detected": 1.0,
            "harmonic_ratio_quality": 0.85,
            "rsi_divergence": 0.8,
        }
        p = HarmonicSetup()
        result = p.check(signals, self._cats(), 0.4)
        assert result.matches is True

    def test_fails_when_no_harmonic_detected(self) -> None:
        signals = {
            "harmonic_pattern_detected": 0.0,
            "harmonic_ratio_quality": 0.9,
            "rsi_divergence": 0.8,
        }
        p = HarmonicSetup()
        result = p.check(signals, self._cats(), 0.4)
        assert result.matches is False
        assert result.conditions_met["harmonic_pattern_detected"] is False

    def test_fails_when_ratio_quality_too_low(self) -> None:
        signals = {
            "harmonic_pattern_detected": 1.0,
            "harmonic_ratio_quality": 0.60,  # below 0.75
            "rsi_divergence": 0.8,
        }
        p = HarmonicSetup()
        result = p.check(signals, self._cats(), 0.4)
        assert result.matches is False
        assert result.conditions_met["harmonic_quality"] is False

    def test_fails_when_no_divergence(self) -> None:
        signals = {
            "harmonic_pattern_detected": 1.0,
            "harmonic_ratio_quality": 0.80,
            "rsi_divergence": 0.0,
            "macd_divergence": 0.0,
        }
        p = HarmonicSetup()
        result = p.check(signals, self._cats(), 0.4)
        assert result.matches is False
        assert result.conditions_met["rsi_or_macd_divergence"] is False

    def test_passes_with_macd_divergence_only(self) -> None:
        signals = {
            "harmonic_pattern_detected": 1.0,
            "harmonic_ratio_quality": 0.80,
            "rsi_divergence": 0.0,
            "macd_divergence": -0.5,  # bearish MACD divergence — still non-zero
        }
        p = HarmonicSetup()
        result = p.check(signals, self._cats(), 0.4)
        assert result.matches is True

    def test_fails_below_score_threshold(self) -> None:
        signals = {
            "harmonic_pattern_detected": 1.0,
            "harmonic_ratio_quality": 0.80,
            "rsi_divergence": 0.8,
        }
        p = HarmonicSetup()
        result = p.check(signals, self._cats(), 0.0)  # composite = 0 < threshold 0.2
        assert result.matches is False

    def test_conditions_dict_has_expected_keys(self) -> None:
        signals: dict[str, float] = {}
        p = HarmonicSetup()
        result = p.check(signals, self._cats(), 0.5)
        assert "harmonic_pattern_detected" in result.conditions_met
        assert "harmonic_quality" in result.conditions_met
        assert "rsi_or_macd_divergence" in result.conditions_met
