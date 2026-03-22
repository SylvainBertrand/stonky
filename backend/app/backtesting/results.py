"""Backtest configuration and result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""

    symbol: str
    timeframe: str  # "1d" | "1w"
    start_date: str  # ISO date
    end_date: str  # ISO date
    strategy_name: str
    strategy_params: dict
    initial_capital: float = 10_000.0
    commission_pct: float = 0.001  # 0.1%
    slippage_pct: float = 0.0005  # 0.05%
    size_type: str = "percent"  # "percent" | "fixed_shares"
    position_size: float = 0.95  # 95% of capital
    allow_shorting: bool = False


@dataclass
class BacktestResult:
    """Complete result of a backtest run."""

    config: BacktestConfig

    # Core stats
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int
    win_rate_pct: float
    profit_factor: float
    total_trades: int
    avg_trade_pct: float
    avg_win_pct: float
    avg_loss_pct: float

    # Time series (for charts)
    equity_curve: list[dict]  # [{date, value}]
    drawdown_curve: list[dict]  # [{date, pct}]

    # Trade log
    trades: list[dict]

    # Benchmark comparison (buy-and-hold)
    benchmark_return_pct: float
    benchmark_sharpe: float
