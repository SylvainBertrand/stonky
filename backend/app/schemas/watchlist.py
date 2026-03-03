from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator


class WatchlistCreate(BaseModel):
    name: str
    description: str | None = None
    is_default: bool = False


class WatchlistRead(BaseModel):
    id: int
    name: str
    description: str | None
    is_default: bool
    created_at: datetime
    item_count: int

    model_config = {"from_attributes": True}


class SymbolAdd(BaseModel):
    ticker: str
    notes: str | None = None

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.strip().upper()


class WatchlistItemRead(BaseModel):
    id: int
    symbol_id: int
    ticker: str
    name: str | None
    notes: str | None
    added_at: datetime

    model_config = {"from_attributes": True}


class WatchlistDetail(BaseModel):
    id: int
    name: str
    description: str | None
    is_default: bool
    created_at: datetime
    item_count: int
    items: list[WatchlistItemRead]

    model_config = {"from_attributes": True}


class WatchlistUpdate(BaseModel):
    name: str


class SetActiveRequest(BaseModel):
    watchlist_id: int


class WatchlistItemWithRatings(BaseModel):
    id: int
    symbol_id: int
    ticker: str
    name: str | None
    notes: str | None
    added_at: datetime
    quant_score: float | None = None
    momentum_grade: str | None = None
    valuation_grade: str | None = None
    growth_grade: str | None = None

    model_config = {"from_attributes": True}


class SAImportResult(BaseModel):
    added: int
    skipped: int
    ratings_imported: int
    errors: int


class IngestionStatusEntry(BaseModel):
    ticker: str
    timeframe: str
    source: str
    bars_fetched: int
    latest_bar: datetime | None
    status: str
    error_message: str | None
    fetched_at: datetime

    model_config = {"from_attributes": True}
