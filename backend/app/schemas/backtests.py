"""Pydantic schemas for backtest API."""

from __future__ import annotations

from datetime import date

from typing import Any

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = "1d"
    start_date: date
    end_date: date
    strategy_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    initial_capital: float = 10_000.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005


class SweepRequest(BacktestRequest):
    param_axes: list[str]
    metric: str = "sharpe_ratio"


class BacktestResponse(BaseModel):
    id: int | None = None
    stats: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    drawdown_curve: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    benchmark_return_pct: float
    benchmark_sharpe: float


class SweepResponse(BaseModel):
    results: list[BacktestResponse]
    best_index: int
    heatmap_data: dict[str, Any]


class BacktestHistoryItem(BaseModel):
    id: int
    created_at: str
    symbol: str
    timeframe: str
    strategy: str
    total_return_pct: float
    sharpe_ratio: float
    total_trades: int
