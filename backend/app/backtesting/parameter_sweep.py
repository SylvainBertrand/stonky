"""Parameter sweep — grid search over strategy parameter combinations."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pandas as pd

from app.backtesting.results import BacktestResult
from app.backtesting.runner import run_backtest_sync


@dataclass
class SweepConfig:
    strategy: object  # StrategyBase instance (used as template)
    param_axes: list[str]  # which 2 params for heatmap
    metric: str = "sharpe_ratio"
    initial_capital: float = 10_000.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005


@dataclass
class SweepResult:
    results: list[BacktestResult]
    best_result: BacktestResult | None
    heatmap_data: dict  # {str(param_combo): metric_value}
    param_combos: list[dict]


def run_sweep_sync(
    df: pd.DataFrame,
    sweep_config: SweepConfig,
) -> SweepResult:
    """Run all parameter combinations from strategy.param_space."""
    strategy = sweep_config.strategy
    param_space = strategy.param_space

    # Generate all combinations
    param_names = list(param_space.keys())
    param_values = [param_space[name] for name in param_names]
    combos = [dict(zip(param_names, vals)) for vals in product(*param_values)]

    results: list[BacktestResult] = []
    param_combos: list[dict] = []

    for combo in combos:
        strategy_cls = type(strategy)
        try:
            if hasattr(strategy, "config"):
                new_strategy = strategy_cls(config=combo)
            else:
                new_strategy = strategy_cls(**combo)
        except TypeError:
            continue

        df_copy = df.copy()
        result = run_backtest_sync(
            df=df_copy,
            strategy=new_strategy,
            initial_capital=sweep_config.initial_capital,
            commission_pct=sweep_config.commission_pct,
            slippage_pct=sweep_config.slippage_pct,
        )
        results.append(result)
        param_combos.append(combo)

    # Find best by metric
    best_result = None
    if results:
        best_idx = max(
            range(len(results)),
            key=lambda i: getattr(results[i], sweep_config.metric, 0),
        )
        best_result = results[best_idx]

    # Build heatmap data for the 2 selected axes
    heatmap_data: dict[str, float] = {}
    if len(sweep_config.param_axes) >= 2:
        ax1, ax2 = sweep_config.param_axes[0], sweep_config.param_axes[1]
        for i, combo in enumerate(param_combos):
            key = str((combo.get(ax1), combo.get(ax2)))
            heatmap_data[key] = getattr(results[i], sweep_config.metric, 0)
    elif len(sweep_config.param_axes) == 1:
        ax1 = sweep_config.param_axes[0]
        for i, combo in enumerate(param_combos):
            key = str((combo.get(ax1),))
            heatmap_data[key] = getattr(results[i], sweep_config.metric, 0)

    return SweepResult(
        results=results,
        best_result=best_result,
        heatmap_data=heatmap_data,
        param_combos=param_combos,
    )
