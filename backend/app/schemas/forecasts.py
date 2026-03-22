"""Pydantic schemas for the Chronos-2 forecast API."""

from __future__ import annotations

from pydantic import BaseModel


class ForecastQuantiles(BaseModel):
    """Forecast quantile bands."""

    median: list[float]
    quantile_10: list[float]
    quantile_25: list[float]
    quantile_75: list[float]
    quantile_90: list[float]


class ForecastResponse(BaseModel):
    """Chronos-2 forecast response for a single symbol."""

    symbol: str
    timeframe: str
    generated_at: str
    last_bar_date: str
    last_close: float
    horizon_bars: int
    direction: str
    direction_confidence: float
    expected_move_pct: float
    forecast: ForecastQuantiles


class ForecastScanRunResponse(BaseModel):
    """Response from triggering a forecast scan."""

    run_id: int
    status: str
    symbols_queued: int


class ForecastScanStatusResponse(BaseModel):
    """Status of a forecast scan run."""

    run_id: int
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    symbols_scanned: int = 0
    symbols_forecast: int = 0
