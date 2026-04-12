"""Chronos-2 probabilistic price forecasting.

Uses amazon/chronos-t5-small to generate probabilistic forecasts of closing
prices. This is a context layer — it does NOT feed the composite scoring engine.

The model is loaded as a module-level singleton on first use (~250MB download).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import torch
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ForecastResult:
    symbol: str
    timeframe: str
    forecast_horizon: int
    generated_at: str
    last_close: float
    last_bar_date: str
    median: list[float]
    quantile_10: list[float]
    quantile_90: list[float]
    quantile_25: list[float]
    quantile_75: list[float]
    direction: str
    direction_confidence: float
    expected_move_pct: float


_pipeline = None


def _get_pipeline() -> Any:
    global _pipeline
    if _pipeline is None:
        from chronos import ChronosPipeline

        log.info("Loading Chronos-2 model (amazon/chronos-t5-small)...")
        _pipeline = ChronosPipeline.from_pretrained(
            "amazon/chronos-t5-small",
            device_map="cpu",
            torch_dtype=torch.float32,
        )
        log.info("Chronos-2 model loaded successfully")
    return _pipeline


MIN_BARS = 50
CONTEXT_WINDOW = 200


def run_forecast(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "1d",
    horizon: int = 20,
    num_samples: int = 50,
) -> ForecastResult | None:
    """Run Chronos-2 forecast on closing prices.

    Returns ForecastResult or None if insufficient data (<50 bars).
    """
    if len(df) < MIN_BARS:
        log.info("Forecast %s: insufficient data (%d bars < %d min)", symbol, len(df), MIN_BARS)
        return None

    closes = df["close"].values[-CONTEXT_WINDOW:].astype(np.float64)
    last_close = float(closes[-1])
    last_bar_date = str(df["time"].iloc[-1])

    pipeline = _get_pipeline()

    context = torch.tensor(closes, dtype=torch.float32).unsqueeze(0)

    try:
        forecast_samples = pipeline.predict(
            context,
            prediction_length=horizon,
            num_samples=num_samples,
        )
        samples = forecast_samples.squeeze(0).numpy()
    except Exception as exc:
        log.error("Forecast %s: inference failed: %s", symbol, exc)
        return None

    median = np.quantile(samples, 0.50, axis=0).tolist()
    quantile_10 = np.quantile(samples, 0.10, axis=0).tolist()
    quantile_25 = np.quantile(samples, 0.25, axis=0).tolist()
    quantile_75 = np.quantile(samples, 0.75, axis=0).tolist()
    quantile_90 = np.quantile(samples, 0.90, axis=0).tolist()

    expected_move = (median[-1] - last_close) / last_close
    expected_move_pct = expected_move * 100

    if expected_move > 0.02:
        direction = "bullish"
    elif expected_move < -0.02:
        direction = "bearish"
    else:
        direction = "neutral"

    final_values = samples[:, -1]
    if direction == "bullish":
        direction_confidence = float(np.mean(final_values > last_close))
    elif direction == "bearish":
        direction_confidence = float(np.mean(final_values < last_close))
    else:
        within_band = np.abs(final_values - last_close) / last_close < 0.02
        direction_confidence = float(np.mean(within_band))

    return ForecastResult(
        symbol=symbol,
        timeframe=timeframe,
        forecast_horizon=horizon,
        generated_at=datetime.now(UTC).isoformat(),
        last_close=last_close,
        last_bar_date=last_bar_date,
        median=[round(v, 4) for v in median],
        quantile_10=[round(v, 4) for v in quantile_10],
        quantile_25=[round(v, 4) for v in quantile_25],
        quantile_75=[round(v, 4) for v in quantile_75],
        quantile_90=[round(v, 4) for v in quantile_90],
        direction=direction,
        direction_confidence=round(direction_confidence, 4),
        expected_move_pct=round(expected_move_pct, 4),
    )
