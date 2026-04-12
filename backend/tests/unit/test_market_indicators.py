"""Tests for broad market indicator computation."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.market.indicators import (
    compute_breadth,
    compute_macro,
    compute_momentum,
    compute_sentiment,
)
from app.market.regime import classify_regime


def _make_close_series(n: int, start: float, drift: float, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, 0.01, n)
    prices = start * np.exp(np.cumsum(returns))
    dates = pd.bdate_range("2024-01-02", periods=n)
    return pd.Series(prices, index=dates, name="close")


@pytest.mark.unit
class TestComputeBreadth:
    def test_ratio_length(self):
        spx = _make_close_series(252, 4500, 0.001)
        rsp = _make_close_series(252, 160, 0.0005, seed=43)
        result = compute_breadth(spx, rsp)
        assert "ratio" in result
        assert len(result["ratio"]) == 252

    def test_broad_signal_when_rsp_outperforms(self):
        spx = _make_close_series(100, 4500, 0.0005)
        rsp = _make_close_series(100, 160, 0.002, seed=43)
        result = compute_breadth(spx, rsp)
        assert result["signal"] in ("broad", "narrow", "neutral")

    def test_ma_columns_present(self):
        spx = _make_close_series(60, 4500, 0.001)
        rsp = _make_close_series(60, 160, 0.001, seed=43)
        result = compute_breadth(spx, rsp)
        assert "ratio_ma20" in result
        assert "ratio_ma50" in result


@pytest.mark.unit
class TestComputeMomentum:
    def test_rsi_in_range(self):
        spx = _make_close_series(100, 4500, 0.001)
        qqq = _make_close_series(100, 380, 0.001, seed=43)
        vix = _make_close_series(100, 18, -0.001, seed=44)
        result = compute_momentum(spx, qqq, vix)
        assert 0 <= result["spx_rsi"] <= 100
        assert 0 <= result["qqq_rsi"] <= 100

    def test_vix_level_label(self):
        spx = _make_close_series(100, 4500, 0.001)
        qqq = _make_close_series(100, 380, 0.001, seed=43)
        vix_low = pd.Series([12.0] * 100, index=pd.bdate_range("2024-01-02", periods=100))
        result = compute_momentum(spx, qqq, vix_low)
        assert result["vix_level_label"] == "complacent"


@pytest.mark.unit
class TestComputeMacro:
    def test_yield_curve_spread(self):
        dates = [date(2025, 1, i + 1) for i in range(30)]
        dgs10 = pd.DataFrame({"date": dates, "value": [4.5] * 30})
        dgs2 = pd.DataFrame({"date": dates, "value": [4.0] * 30})
        result = compute_macro(dgs10, dgs2, pd.DataFrame(), pd.Series(dtype=float))
        assert result["yield_spread"] == pytest.approx(0.5)
        assert result["yield_curve_label"] == "normal"

    def test_inverted_yield_curve(self):
        dates = [date(2025, 1, i + 1) for i in range(30)]
        dgs10 = pd.DataFrame({"date": dates, "value": [3.8] * 30})
        dgs2 = pd.DataFrame({"date": dates, "value": [4.5] * 30})
        result = compute_macro(dgs10, dgs2, pd.DataFrame(), pd.Series(dtype=float))
        assert result["yield_spread"] == pytest.approx(-0.7)
        assert result["yield_curve_label"] == "inverted"

    def test_empty_fred_data(self):
        result = compute_macro(
            pd.DataFrame(columns=["date", "value"]),
            pd.DataFrame(columns=["date", "value"]),
            pd.DataFrame(columns=["date", "value"]),
            pd.Series(dtype=float),
        )
        assert result["yield_spread"] is None
        assert result["yield_curve_label"] == "unavailable"


@pytest.mark.unit
class TestComputeSentiment:
    def test_bull_bear_spread(self):
        readings = [
            {"week_ending": date(2025, 1, 2), "spread": 25.0},
            {"week_ending": date(2025, 1, 9), "spread": 22.0},
            {"week_ending": date(2025, 1, 16), "spread": 18.0},
            {"week_ending": date(2025, 1, 23), "spread": 20.0},
        ]
        result = compute_sentiment(readings, [])
        assert result["aaii_latest_spread"] == pytest.approx(20.0)
        assert "aaii_4wk_ma" in result

    def test_empty_sentiment(self):
        result = compute_sentiment([], [])
        assert result["aaii_latest_spread"] is None
        assert result["naaim_latest"] is None


@pytest.mark.unit
class TestClassifyRegime:
    def test_bull_trending(self):
        regime = classify_regime(
            spx_above_200ema=True,
            spx_rsi=60.0,
            breadth="broad",
            vix=16.0,
            yield_inverted_months=0,
            aaii_spread=5.0,
            naaim_exposure=65.0,
        )
        assert regime.regime == "bull_trending"

    def test_bear(self):
        regime = classify_regime(
            spx_above_200ema=False,
            spx_rsi=35.0,
            breadth="narrow",
            vix=30.0,
            yield_inverted_months=6,
            aaii_spread=-15.0,
            naaim_exposure=40.0,
        )
        assert regime.regime == "bear"

    def test_choppy(self):
        regime = classify_regime(
            spx_above_200ema=True,
            spx_rsi=55.0,
            breadth="neutral",
            vix=22.0,
            yield_inverted_months=0,
            aaii_spread=0.0,
            naaim_exposure=60.0,
        )
        assert regime.regime == "choppy"

    def test_regime_has_summary(self):
        regime = classify_regime(
            spx_above_200ema=True,
            spx_rsi=60.0,
            breadth="broad",
            vix=16.0,
            yield_inverted_months=0,
            aaii_spread=5.0,
            naaim_exposure=65.0,
        )
        assert len(regime.summary) > 0
        assert len(regime.scanner_implication) > 0

    def test_regime_with_missing_data(self):
        regime = classify_regime(
            spx_above_200ema=True,
            spx_rsi=60.0,
            breadth="broad",
            vix=16.0,
            yield_inverted_months=None,
            aaii_spread=None,
            naaim_exposure=None,
        )
        assert regime.regime in ("bull_trending", "bull_extended", "choppy", "bear_warning", "bear")
