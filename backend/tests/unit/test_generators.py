"""
Unit tests for synthetic OHLCV generators — pure logic, no I/O.

Validates:
- Correct column names and dtypes
- Determinism (same seed → same output)
- Shape-specific properties (uptrend goes up, consolidation stays in range, etc.)
"""

import numpy as np
import pytest

from tests.generators import (
    gen_breakout,
    gen_bullish_engulfing,
    gen_consolidation,
    gen_double_top,
    gen_downtrend,
    gen_harmonic_gartley,
    gen_uptrend,
    gen_v_recovery,
)

_ALL_GENERATORS = [
    gen_uptrend,
    gen_downtrend,
    gen_consolidation,
    gen_v_recovery,
    gen_breakout,
    gen_harmonic_gartley,
    gen_double_top,
    gen_bullish_engulfing,
]

_EXPECTED_COLUMNS = {"time", "open", "high", "low", "close", "volume"}


@pytest.mark.unit
@pytest.mark.parametrize("generator", _ALL_GENERATORS, ids=lambda f: f.__name__)
class TestGeneratorShape:
    def test_has_required_columns(self, generator) -> None:  # type: ignore[no-untyped-def]
        df = generator()
        assert set(df.columns) >= _EXPECTED_COLUMNS, (
            f"{generator.__name__} is missing columns: "
            f"{_EXPECTED_COLUMNS - set(df.columns)}"
        )

    def test_no_nan_in_ohlcv(self, generator) -> None:  # type: ignore[no-untyped-def]
        df = generator()
        ohlcv = df[["open", "high", "low", "close", "volume"]]
        assert not ohlcv.isnull().any().any(), f"{generator.__name__} contains NaN values"

    def test_high_gte_low(self, generator) -> None:  # type: ignore[no-untyped-def]
        df = generator()
        bad = (df["high"] < df["low"]).sum()
        assert bad == 0, f"{generator.__name__}: {bad} bars where high < low"

    def test_high_gte_open_and_close(self, generator) -> None:  # type: ignore[no-untyped-def]
        df = generator()
        assert (df["high"] >= df["open"]).all()
        assert (df["high"] >= df["close"]).all()

    def test_low_lte_open_and_close(self, generator) -> None:  # type: ignore[no-untyped-def]
        df = generator()
        assert (df["low"] <= df["open"]).all()
        assert (df["low"] <= df["close"]).all()

    def test_volume_positive(self, generator) -> None:  # type: ignore[no-untyped-def]
        df = generator()
        assert (df["volume"] > 0).all(), f"{generator.__name__} has non-positive volume"

    def test_deterministic_same_seed(self, generator) -> None:  # type: ignore[no-untyped-def]
        df1 = generator(seed=99)
        df2 = generator(seed=99)
        assert df1.equals(df2), f"{generator.__name__} is not deterministic with same seed"

    def test_different_seeds_differ(self, generator) -> None:  # type: ignore[no-untyped-def]
        df1 = generator(seed=1)
        df2 = generator(seed=2)
        # At least close prices should differ
        assert not df1["close"].equals(df2["close"]), (
            f"{generator.__name__} produces identical output for different seeds"
        )


@pytest.mark.unit
class TestTrendProperties:
    def test_uptrend_ends_higher_than_start(self) -> None:
        df = gen_uptrend(bars=100, seed=42)
        assert df["close"].iloc[-1] > df["close"].iloc[0], (
            "gen_uptrend: last close should be higher than first close"
        )

    def test_downtrend_ends_lower_than_start(self) -> None:
        df = gen_downtrend(bars=100, seed=42)
        assert df["close"].iloc[-1] < df["close"].iloc[0], (
            "gen_downtrend: last close should be lower than first close"
        )

    def test_consolidation_stays_within_range(self) -> None:
        base = 120.0
        df = gen_consolidation(bars=100, seed=42, base_price=base)
        # Consolidation should stay within ±10% of base price
        tolerance = base * 0.10
        assert df["close"].max() < base + tolerance, "gen_consolidation drifted too high"
        assert df["close"].min() > base - tolerance, "gen_consolidation drifted too low"

    def test_v_recovery_has_dip_and_recovery(self) -> None:
        base = 130.0
        df = gen_v_recovery(
            bars=100, seed=42, base_price=base, drop_start=30, drop_duration=15
        )
        # Should have a low below base
        assert df["close"].min() < base, "gen_v_recovery: no dip below base price"
        # Should recover — last price higher than the dip
        assert df["close"].iloc[-1] > df["close"].min() * 1.05, (
            "gen_v_recovery: no recovery detected"
        )

    def test_breakout_expansion(self) -> None:
        df = gen_breakout(bars=100, seed=42, breakout_bar=60)
        # Pre-breakout range should be tighter than post-breakout range
        pre_range = df["high"].iloc[:60].max() - df["low"].iloc[:60].min()
        post_range = df["high"].iloc[60:].max() - df["low"].iloc[60:].min()
        assert post_range > pre_range, (
            "gen_breakout: post-breakout range not wider than pre-breakout"
        )

    def test_gartley_has_five_legs(self) -> None:
        df = gen_harmonic_gartley(bars_per_leg=15)
        # 5 legs × 15 bars = 75 bars
        assert len(df) == 75

    def test_double_top_has_two_peaks(self) -> None:
        df = gen_double_top(bars=100, seed=42, peak_price=125.0)
        # There should be a clear peak in first half and another in second-to-last quarter
        first_quarter_max = df["close"].iloc[: len(df) // 4].max()
        second_quarter_max = df["close"].iloc[len(df) // 2 : 3 * len(df) // 4].max()
        # Both should be near the peak price
        assert first_quarter_max > 120.0, "gen_double_top: first peak not found"
        assert second_quarter_max > 120.0, "gen_double_top: second peak not found"

    def test_bullish_engulfing_last_candle_is_bullish(self) -> None:
        df = gen_bullish_engulfing(bars=50, seed=42)
        last = df.iloc[-1]
        # Engulfing candle: close > open (bullish body)
        assert last["close"] > last["open"], (
            "gen_bullish_engulfing: last candle is not bullish"
        )

    def test_bullish_engulfing_volume_spike(self) -> None:
        df = gen_bullish_engulfing(bars=50, seed=42)
        avg_volume = df["volume"].iloc[:-1].mean()
        last_volume = df["volume"].iloc[-1]
        assert last_volume > avg_volume * 1.5, (
            "gen_bullish_engulfing: expected volume spike on engulfing candle"
        )
