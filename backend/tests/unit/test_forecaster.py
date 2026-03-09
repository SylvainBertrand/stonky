"""Unit tests for Chronos-2 price forecasting.

Tests cover:
- run_forecast() direction classification
- run_forecast() quantile computation
- run_forecast() edge cases (insufficient data)
- Direction confidence calculation
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ohlcv_df(
    n_bars: int = 200,
    start_price: float = 100.0,
    trend: float = 0.001,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    closes = start_price * np.exp(np.cumsum(trend + rng.normal(0, 0.01, n_bars)))
    opens = closes * (1 + rng.normal(0, 0.005, n_bars))
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.01, n_bars))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.01, n_bars))
    volumes = rng.uniform(1e6, 5e6, n_bars)
    dates = pd.bdate_range(end="2026-03-04", periods=n_bars)
    return pd.DataFrame({
        "time": [d.strftime("%Y-%m-%d") for d in dates],
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def _mock_pipeline_predict(closes: np.ndarray, horizon: int, num_samples: int):
    """Return a mock forecast tensor shaped (1, num_samples, horizon).
    Simulates a bullish forecast: slight upward drift from last close.
    """
    import torch
    last = closes[-1]
    drift = np.linspace(0, 0.05, horizon)
    noise = np.random.default_rng(42).normal(0, 0.01, (num_samples, horizon))
    samples = last * (1 + drift[np.newaxis, :] + noise)
    return torch.tensor(samples).unsqueeze(0)


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRunForecast:
    """Tests for run_forecast()."""

    @patch("app.analysis.forecaster._get_pipeline")
    def test_bullish_forecast(self, mock_get_pipeline: MagicMock) -> None:
        """Upward-drifting samples → bullish direction."""
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=200, trend=0.001)
        last_close = df["close"].iloc[-1]

        mock_pipeline = MagicMock()
        mock_pipeline.predict.side_effect = (
            lambda context, prediction_length, num_samples, **kw:
                _mock_pipeline_predict(
                    df["close"].values, prediction_length, num_samples
                )
        )
        mock_get_pipeline.return_value = mock_pipeline

        result = run_forecast(df, "TEST", timeframe="1d", horizon=20, num_samples=50)

        assert result is not None
        assert result.symbol == "TEST"
        assert result.direction == "bullish"
        assert result.direction_confidence > 0.5
        assert result.expected_move_pct > 0
        assert len(result.median) == 20
        assert len(result.quantile_10) == 20
        assert len(result.quantile_90) == 20
        assert result.last_close == pytest.approx(last_close, rel=1e-6)

    @patch("app.analysis.forecaster._get_pipeline")
    def test_bearish_forecast(self, mock_get_pipeline: MagicMock) -> None:
        """Downward-drifting samples → bearish direction."""
        import torch
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=200)
        last_close = df["close"].iloc[-1]

        mock_pipeline = MagicMock()
        def predict_bearish(context, prediction_length, num_samples, **kw):
            drift = np.linspace(0, -0.05, prediction_length)
            noise = np.random.default_rng(42).normal(0, 0.005, (num_samples, prediction_length))
            samples = last_close * (1 + drift[np.newaxis, :] + noise)
            return torch.tensor(samples).unsqueeze(0)

        mock_pipeline.predict.side_effect = predict_bearish
        mock_get_pipeline.return_value = mock_pipeline

        result = run_forecast(df, "TEST", timeframe="1d", horizon=20, num_samples=50)

        assert result is not None
        assert result.direction == "bearish"
        assert result.expected_move_pct < 0

    @patch("app.analysis.forecaster._get_pipeline")
    def test_neutral_forecast(self, mock_get_pipeline: MagicMock) -> None:
        """Flat samples (within ±2%) → neutral direction."""
        import torch
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=200)
        last_close = df["close"].iloc[-1]

        mock_pipeline = MagicMock()
        def predict_flat(context, prediction_length, num_samples, **kw):
            noise = np.random.default_rng(42).normal(0, 0.002, (num_samples, prediction_length))
            samples = last_close * (1 + noise)
            return torch.tensor(samples).unsqueeze(0)

        mock_pipeline.predict.side_effect = predict_flat
        mock_get_pipeline.return_value = mock_pipeline

        result = run_forecast(df, "TEST", timeframe="1d", horizon=20, num_samples=50)

        assert result is not None
        assert result.direction == "neutral"
        assert abs(result.expected_move_pct) <= 2.0

    def test_insufficient_data_returns_none(self) -> None:
        """Less than 50 bars → None."""
        from app.analysis.forecaster import run_forecast
        df = _make_ohlcv_df(n_bars=30)
        result = run_forecast(df, "TEST")
        assert result is None

    @patch("app.analysis.forecaster._get_pipeline")
    def test_quantile_ordering(self, mock_get_pipeline: MagicMock) -> None:
        """Quantiles must be ordered: q10 <= q25 <= median <= q75 <= q90."""
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=200)
        mock_pipeline = MagicMock()
        mock_pipeline.predict.side_effect = (
            lambda context, prediction_length, num_samples, **kw:
                _mock_pipeline_predict(
                    df["close"].values, prediction_length, num_samples
                )
        )
        mock_get_pipeline.return_value = mock_pipeline

        result = run_forecast(df, "TEST", horizon=20, num_samples=50)
        assert result is not None

        for i in range(len(result.median)):
            assert result.quantile_10[i] <= result.quantile_25[i]
            assert result.quantile_25[i] <= result.median[i]
            assert result.median[i] <= result.quantile_75[i]
            assert result.quantile_75[i] <= result.quantile_90[i]

    @patch("app.analysis.forecaster._get_pipeline")
    def test_forecast_result_fields(self, mock_get_pipeline: MagicMock) -> None:
        """ForecastResult has all required fields."""
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=200)
        mock_pipeline = MagicMock()
        mock_pipeline.predict.side_effect = (
            lambda context, prediction_length, num_samples, **kw:
                _mock_pipeline_predict(
                    df["close"].values, prediction_length, num_samples
                )
        )
        mock_get_pipeline.return_value = mock_pipeline

        result = run_forecast(df, "TEST", timeframe="1d", horizon=20, num_samples=50)
        assert result is not None

        assert result.timeframe == "1d"
        assert result.forecast_horizon == 20
        assert result.last_bar_date == "2026-03-04"
        assert result.direction in ("bullish", "bearish", "neutral")
        assert 0.0 <= result.direction_confidence <= 1.0
