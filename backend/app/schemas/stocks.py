"""Pydantic schemas for stocks API endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StockPriceResponse(BaseModel):
    """Real-time current price quote for a single symbol."""

    symbol: str = Field(..., description="Uppercase ticker symbol")
    price: float = Field(..., description="Last traded price")
    change_abs: float = Field(..., description="Absolute change vs previous close")
    change_pct: float = Field(..., description="Percent change vs previous close")
    timestamp: float = Field(..., description="Unix epoch seconds (UTC) when the quote was fetched")
