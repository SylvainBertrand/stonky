"""Pydantic schemas for market API endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class MarketRegimeResponse(BaseModel):
    as_of_date: str | None = None
    regime: str
    breadth: str
    momentum: str
    sentiment: str
    macro: str
    summary: str
    scanner_implication: str


class TimeSeriesItem(BaseModel):
    name: str
    data: list[float | None]


class TimeSeriesResponse(BaseModel):
    labels: list[str]
    series: list[TimeSeriesItem]


class SentimentImportResponse(BaseModel):
    source: str
    rows_imported: int


class RefreshStatusResponse(BaseModel):
    status: str
    last_refreshed: str | None = None
