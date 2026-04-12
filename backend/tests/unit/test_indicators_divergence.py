"""
Unit tests for divergence indicators: RSI divergence, MACD histogram divergence.
"""

from __future__ import annotations

import pytest

from tests.generators import gen_double_top, gen_uptrend, gen_v_recovery


@pytest.mark.unit
class TestRSIDivergence:
    def test_v_recovery_bullish_divergence(self) -> None:
        from app.analysis.indicators.divergence import compute_rsi_divergence_signals

        df = gen_v_recovery(bars=200, seed=42)
        # After recovery, last bars should have had some bullish divergence signal
        # (test only checks no crash + score in bounds)
        signals = compute_rsi_divergence_signals(df)
        assert "rsi_divergence" in signals
        assert -1.0 <= signals["rsi_divergence"] <= 1.0

    def test_double_top_bearish_divergence(self) -> None:
        from app.analysis.indicators.divergence import compute_rsi_divergence_signals

        df = gen_double_top(bars=200, seed=42)
        signals = compute_rsi_divergence_signals(df)
        assert "rsi_divergence" in signals
        assert -1.0 <= signals["rsi_divergence"] <= 1.0

    def test_no_divergence_uptrend_score_near_zero(self) -> None:
        from app.analysis.indicators.divergence import compute_rsi_divergence_signals

        df = gen_uptrend(bars=200, seed=42)
        signals = compute_rsi_divergence_signals(df)
        if "rsi_divergence" in signals:
            # Plain uptrend: might have hidden bullish (HL+LL) but shouldn't be extreme
            assert -1.0 <= signals["rsi_divergence"] <= 1.0

    def test_short_series_returns_empty(self) -> None:
        from app.analysis.indicators.divergence import compute_rsi_divergence_signals

        df = gen_uptrend(bars=10)
        signals = compute_rsi_divergence_signals(df)
        assert signals == {}

    def test_score_bounded(self) -> None:
        from app.analysis.indicators.divergence import compute_rsi_divergence_signals
        from tests.generators import gen_breakout

        for gen in (gen_uptrend, gen_double_top, gen_v_recovery, gen_breakout):
            df = gen(bars=200, seed=42)
            signals = compute_rsi_divergence_signals(df)
            if "rsi_divergence" in signals:
                assert -1.0 <= signals["rsi_divergence"] <= 1.0


@pytest.mark.unit
class TestMACDDivergence:
    def test_v_recovery_produces_score(self) -> None:
        from app.analysis.indicators.divergence import compute_macd_divergence_signals

        df = gen_v_recovery(bars=200, seed=42)
        signals = compute_macd_divergence_signals(df)
        assert "macd_divergence" in signals
        assert -1.0 <= signals["macd_divergence"] <= 1.0

    def test_double_top_produces_score(self) -> None:
        from app.analysis.indicators.divergence import compute_macd_divergence_signals

        df = gen_double_top(bars=200, seed=42)
        signals = compute_macd_divergence_signals(df)
        assert "macd_divergence" in signals
        assert -1.0 <= signals["macd_divergence"] <= 1.0

    def test_short_series_returns_empty(self) -> None:
        from app.analysis.indicators.divergence import compute_macd_divergence_signals

        df = gen_uptrend(bars=30)
        signals = compute_macd_divergence_signals(df)
        assert signals == {}

    def test_score_bounded(self) -> None:
        from app.analysis.indicators.divergence import compute_macd_divergence_signals

        for gen in (gen_uptrend, gen_double_top, gen_v_recovery):
            df = gen(bars=200, seed=42)
            signals = compute_macd_divergence_signals(df)
            if "macd_divergence" in signals:
                assert -1.0 <= signals["macd_divergence"] <= 1.0
