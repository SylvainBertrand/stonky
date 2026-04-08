"""Pydantic schemas for the indicators API endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IndicatorValuesResponse(BaseModel):
    """
    Latest-bar raw indicator values for a single symbol/timeframe.

    `indicators` is a flat map of indicator name → numeric value. Values may
    be `null` when the underlying series has insufficient bars to compute
    (e.g. EMA-200 needs ≥200 bars) or when pandas-ta failed to populate the
    column. Callers should treat `null` as "no signal" rather than zero.
    """

    symbol: str = Field(..., description="Uppercase ticker symbol")
    timeframe: str = Field(..., description="Requested timeframe (e.g. '1d')")
    timestamp: str = Field(
        ..., description="ISO 8601 datetime of the latest bar used for computation"
    )
    indicators: dict[str, float | None] = Field(
        ..., description="Indicator name → latest-bar numeric value (or null)"
    )
