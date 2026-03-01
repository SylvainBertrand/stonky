"""
Unit tests for trend indicators: EMA, ADX/DMI, Supertrend.
"""

from __future__ import annotations

import pytest

from tests.generators import gen_consolidation, gen_downtrend, gen_uptrend


@pytest.mark.unit
class TestEMAIndicator:
    def test_ema_columns_present(self) -> None:
        from app.analysis.indicators.trend import compute_ema
        df = gen_uptrend(bars=250, seed=42)
        result = compute_ema(df)
        for col in ("ema_21", "ema_50", "ema_200"):
            assert col in result.columns, f"Missing column: {col}"

    def test_ema_not_nan_after_warmup(self) -> None:
        from app.analysis.indicators.trend import compute_ema
        df = gen_uptrend(bars=250, seed=42)
        result = compute_ema(df)
        assert result["ema_200"].iloc[-1] is not None
        import pandas as pd
        assert not pd.isna(result["ema_200"].iloc[-1])

    def test_ema_score_plus_one_in_uptrend(self) -> None:
        from app.analysis.indicators.trend import compute_ema_signals
        df = gen_uptrend(bars=250, seed=42)
        signals = compute_ema_signals(df)
        assert "ema_stack" in signals
        assert signals["ema_stack"] == pytest.approx(1.0), (
            f"Expected +1.0 for uptrend EMA stack, got {signals['ema_stack']}"
        )

    def test_ema_score_minus_one_in_downtrend(self) -> None:
        from app.analysis.indicators.trend import compute_ema_signals
        df = gen_downtrend(bars=250, seed=42)
        signals = compute_ema_signals(df)
        assert "ema_stack" in signals
        assert signals["ema_stack"] == pytest.approx(-1.0), (
            f"Expected -1.0 for downtrend EMA stack, got {signals['ema_stack']}"
        )

    def test_ema_score_bounded(self) -> None:
        from app.analysis.indicators.trend import compute_ema_signals
        for gen in (gen_uptrend, gen_downtrend, gen_consolidation):
            df = gen(bars=250, seed=42)
            signals = compute_ema_signals(df)
            if "ema_stack" in signals:
                assert -1.0 <= signals["ema_stack"] <= 1.0

    def test_ema_short_series_returns_empty(self) -> None:
        from app.analysis.indicators.trend import compute_ema_signals
        df = gen_uptrend(bars=10, seed=42)
        signals = compute_ema_signals(df)
        assert signals == {}


@pytest.mark.unit
class TestADXIndicator:
    def test_adx_columns_present(self) -> None:
        from app.analysis.indicators.trend import compute_adx
        df = gen_uptrend(bars=100, seed=42)
        result = compute_adx(df)
        for col in ("adx", "dmp_14", "dmn_14"):
            assert col in result.columns, f"Missing column: {col}"

    def test_adx_score_near_zero_for_consolidation(self) -> None:
        from app.analysis.indicators.trend import compute_adx_signals
        df = gen_consolidation(bars=100, seed=42)
        signals = compute_adx_signals(df)
        if "adx_dmi" in signals:
            assert abs(signals["adx_dmi"]) <= 0.5, (
                f"ADX score should be low for consolidation, got {signals['adx_dmi']}"
            )

    def test_adx_score_bullish_for_uptrend(self) -> None:
        from app.analysis.indicators.trend import compute_adx_signals
        df = gen_uptrend(bars=200, seed=42)
        signals = compute_adx_signals(df)
        if "adx_dmi" in signals:
            assert signals["adx_dmi"] >= 0.0, (
                f"ADX/DMI should be bullish for uptrend, got {signals['adx_dmi']}"
            )

    def test_adx_score_bounded(self) -> None:
        from app.analysis.indicators.trend import compute_adx_signals
        df = gen_uptrend(bars=200, seed=42)
        signals = compute_adx_signals(df)
        if "adx_dmi" in signals:
            assert -1.0 <= signals["adx_dmi"] <= 1.0


@pytest.mark.unit
class TestSupertrendIndicator:
    def test_supertrend_column_present(self) -> None:
        from app.analysis.indicators.trend import compute_supertrend
        df = gen_uptrend(bars=100, seed=42)
        result = compute_supertrend(df)
        assert "supertrend_dir" in result.columns

    def test_supertrend_binary_signal(self) -> None:
        from app.analysis.indicators.trend import compute_supertrend_signals
        for gen, expected_sign in [(gen_uptrend, 1.0), (gen_downtrend, -1.0)]:
            df = gen(bars=200, seed=42)
            signals = compute_supertrend_signals(df)
            if "supertrend" in signals:
                assert signals["supertrend"] in (-1.0, 1.0), (
                    f"Supertrend should be binary ±1, got {signals['supertrend']}"
                )

    def test_supertrend_bullish_for_uptrend(self) -> None:
        from app.analysis.indicators.trend import compute_supertrend_signals
        df = gen_uptrend(bars=200, seed=42)
        signals = compute_supertrend_signals(df)
        if "supertrend" in signals:
            assert signals["supertrend"] == pytest.approx(1.0), (
                f"Expected bullish Supertrend for uptrend, got {signals['supertrend']}"
            )
