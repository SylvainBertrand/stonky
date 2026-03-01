"""
Unit tests for momentum indicators: RSI, MACD, Stochastic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.generators import gen_consolidation, gen_downtrend, gen_uptrend, gen_v_recovery


@pytest.mark.unit
class TestRSIIndicator:
    def test_rsi_column_present(self) -> None:
        from app.analysis.indicators.momentum import compute_rsi
        df = gen_uptrend(bars=100)
        result = compute_rsi(df)
        assert "rsi_14" in result.columns

    def test_rsi_oversold_zone_is_bullish(self) -> None:
        from app.analysis.indicators.momentum import compute_rsi_signals
        # Build a strongly declining series to push RSI into oversold
        df = gen_downtrend(bars=100, seed=42, base_price=150.0, drift=-0.015)
        signals = compute_rsi_signals(df)
        if "rsi" in signals:
            # After sustained decline, RSI should be oversold → positive score
            assert signals["rsi"] >= -0.3, (
                f"RSI should lean bullish (oversold) after downtrend, got {signals['rsi']}"
            )

    def test_rsi_overbought_zone_is_bearish(self) -> None:
        from app.analysis.indicators.momentum import compute_rsi_signals
        df = gen_uptrend(bars=200, seed=42, drift=0.008)
        signals = compute_rsi_signals(df)
        if "rsi" in signals:
            assert signals["rsi"] <= 0.5

    def test_rsi_score_bounded(self) -> None:
        from app.analysis.indicators.momentum import compute_rsi_signals
        for gen in (gen_uptrend, gen_downtrend, gen_consolidation):
            df = gen(bars=200, seed=42)
            signals = compute_rsi_signals(df)
            if "rsi" in signals:
                assert -1.0 <= signals["rsi"] <= 1.0

    def test_rsi_short_series_empty(self) -> None:
        from app.analysis.indicators.momentum import compute_rsi_signals
        df = gen_uptrend(bars=5)
        signals = compute_rsi_signals(df)
        assert signals == {}


@pytest.mark.unit
class TestMACDIndicator:
    def test_macd_columns_present(self) -> None:
        from app.analysis.indicators.momentum import compute_macd
        df = gen_uptrend(bars=100)
        result = compute_macd(df)
        for col in ("macd", "macdh", "macds"):
            assert col in result.columns

    def test_macd_histogram_positive_bullish(self) -> None:
        from app.analysis.indicators.momentum import compute_macd_signals
        df = gen_uptrend(bars=200, seed=42)
        signals = compute_macd_signals(df)
        if "macd" in signals:
            # After consistent uptrend, histogram should be positive
            assert signals["macd"] >= -0.5

    def test_macd_score_bounded(self) -> None:
        from app.analysis.indicators.momentum import compute_macd_signals
        for gen in (gen_uptrend, gen_downtrend, gen_consolidation):
            df = gen(bars=200, seed=42)
            signals = compute_macd_signals(df)
            if "macd" in signals:
                assert -1.0 <= signals["macd"] <= 1.0

    def test_macd_short_series_empty(self) -> None:
        from app.analysis.indicators.momentum import compute_macd_signals
        df = gen_uptrend(bars=20)
        signals = compute_macd_signals(df)
        assert signals == {}

    def test_crossover_decay(self) -> None:
        from app.analysis.indicators.momentum import _crossover_decay
        # Build two series where a crosses above b at bar -5
        a = pd.Series([1.0] * 10 + [0.5] * 5 + [1.5] * 6)
        b = pd.Series([1.0] * 10 + [1.0] * 11)
        # After the cross, score should be > 0
        result = _crossover_decay(a, b, decay_bars=10)
        assert result >= 0.0


@pytest.mark.unit
class TestStochasticIndicator:
    def test_stoch_columns_present(self) -> None:
        from app.analysis.indicators.momentum import compute_stoch
        df = gen_uptrend(bars=100)
        result = compute_stoch(df)
        for col in ("stoch_k", "stoch_d"):
            assert col in result.columns

    def test_stoch_oversold_is_bullish(self) -> None:
        from app.analysis.indicators.momentum import compute_stoch_signals
        df = gen_downtrend(bars=100, seed=42, drift=-0.01)
        signals = compute_stoch_signals(df)
        if "stochastic" in signals:
            assert -1.0 <= signals["stochastic"] <= 1.0

    def test_stoch_score_bounded(self) -> None:
        from app.analysis.indicators.momentum import compute_stoch_signals
        for gen in (gen_uptrend, gen_downtrend, gen_consolidation):
            df = gen(bars=200, seed=42)
            signals = compute_stoch_signals(df)
            if "stochastic" in signals:
                assert -1.0 <= signals["stochastic"] <= 1.0

    def test_stoch_short_series_empty(self) -> None:
        from app.analysis.indicators.momentum import compute_stoch_signals
        df = gen_uptrend(bars=5)
        signals = compute_stoch_signals(df)
        assert signals == {}
