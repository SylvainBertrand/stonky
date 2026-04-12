"""Backtest runner — orchestrates indicator enrichment and portfolio simulation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from app.analysis.indicators.harmonics import detect_harmonics
from app.analysis.indicators.momentum import compute_macd, compute_rsi, compute_stoch

# Indicator compute functions
from app.analysis.indicators.trend import compute_adx, compute_ema, compute_supertrend
from app.analysis.indicators.volatility import (
    compute_atr,
    compute_bbands,
    compute_ttm_squeeze,
)
from app.analysis.indicators.volume import compute_cmf, compute_obv, compute_vwap
from app.backtesting.results import BacktestConfig, BacktestResult
from app.backtesting.strategies.base import StrategyBase


def enrich_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Call all compute_*() functions to add indicator columns to the DataFrame.

    Each compute_*() function returns a new DataFrame (it does df.copy() internally),
    so this function chains their return values. The caller receives the fully enriched
    DataFrame — it should always use the return value:

        df = enrich_dataframe(df)
    """
    df = compute_ema(df)
    df = compute_adx(df)
    df = compute_supertrend(df)
    df = compute_rsi(df)
    df = compute_macd(df)
    df = compute_stoch(df)
    df = compute_bbands(df)
    df = compute_atr(df)
    df = compute_ttm_squeeze(df)
    df = compute_obv(df)
    df = compute_vwap(df)
    df = compute_cmf(df)

    # Materialize harmonic patterns into DataFrame columns
    _materialize_harmonics(df)

    return df


def _materialize_harmonics(df: pd.DataFrame) -> None:
    """Run detect_harmonics() and write results as DataFrame columns."""
    df["harmonic_detected"] = False
    df["harmonic_score"] = 0.0
    df["harmonic_prz_low"] = np.nan
    df["harmonic_prz_high"] = np.nan
    df["harmonic_x_price"] = np.nan

    try:
        matches = detect_harmonics(df, max_bars_since_completion=len(df), min_ratio_quality=0.3)
    except Exception:
        return

    for m in matches:
        if 0 <= m.completion_bar < len(df):
            idx = df.index[m.completion_bar]
            df.loc[idx, "harmonic_detected"] = True
            df.loc[idx, "harmonic_score"] = m.ratio_quality
            df.loc[idx, "harmonic_prz_low"] = m.prz_low
            df.loc[idx, "harmonic_prz_high"] = m.prz_high
            df.loc[idx, "harmonic_x_price"] = m.x


def materialize_yolo_detections(df: pd.DataFrame, detections: list[dict[str, Any]]) -> None:
    """Write pre-fetched YOLO pattern_detections into DataFrame columns.

    Called by the API layer after fetching detections from DB.
    Each detection dict has: pattern_name, confidence, bar_end (timestamp), direction.
    """
    df["yolo_pattern"] = None
    df["yolo_confidence"] = 0.0

    for det in detections:
        bar_time = pd.Timestamp(det["bar_end"])
        idx = df.index.get_indexer([bar_time], method="nearest")[0]
        if 0 <= idx < len(df):
            df.iloc[idx, df.columns.get_loc("yolo_pattern")] = det["pattern_name"]
            df.iloc[idx, df.columns.get_loc("yolo_confidence")] = det["confidence"]


def _compute_sharpe(returns: np.ndarray[Any, np.dtype[Any]], periods_per_year: float = 252.0) -> float:
    """Annualized Sharpe ratio from daily returns."""
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns) * np.sqrt(periods_per_year))


def _compute_sortino(returns: np.ndarray[Any, np.dtype[Any]], periods_per_year: float = 252.0) -> float:
    """Annualized Sortino ratio from daily returns."""
    if len(returns) < 2:
        return 0.0
    downside = returns[returns < 0]
    if len(downside) == 0 or np.std(downside) == 0:
        return 0.0 if np.mean(returns) <= 0 else float("inf")
    return float(np.mean(returns) / np.std(downside) * np.sqrt(periods_per_year))


def _compute_cagr(start_value: float, end_value: float, days: int) -> float:
    """Compound annual growth rate."""
    if days <= 0 or start_value <= 0:
        return 0.0
    years = days / 365.25
    if years == 0:
        return 0.0
    return float((end_value / start_value) ** (1 / years) - 1) * 100


def _compute_max_drawdown(equity: np.ndarray[Any, np.dtype[Any]]) -> tuple[float, int]:
    """Returns (max_drawdown_pct, max_drawdown_duration_days)."""
    if len(equity) < 2:
        return 0.0, 0
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_dd = float(np.min(drawdown)) * 100  # negative percentage

    # Duration: longest streak below previous peak
    below_peak = equity < peak
    max_duration = 0
    current_duration = 0
    for bp in below_peak:
        if bp:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0

    return max_dd, max_duration


def _simulate_portfolio(
    close: np.ndarray[Any, np.dtype[Any]],
    entries: np.ndarray[Any, np.dtype[Any]],
    exits: np.ndarray[Any, np.dtype[Any]],
    initial_capital: float,
    commission_pct: float,
    slippage_pct: float,
    position_size_pct: float = 0.95,
) -> tuple[np.ndarray[Any, np.dtype[Any]], list[dict[str, Any]]]:
    """Simple long-only portfolio simulation. Returns (equity_array, trade_list)."""
    n = len(close)
    equity = np.full(n, initial_capital, dtype=float)
    cash = initial_capital
    shares = 0.0
    in_position = False
    entry_price = 0.0
    entry_bar = 0
    trades: list[dict[str, Any]] = []

    for i in range(n):
        # Update equity
        if in_position:
            equity[i] = cash + shares * close[i]
        else:
            equity[i] = cash

        # Check exit first
        if in_position and exits[i]:
            sell_price = close[i] * (1 - slippage_pct)
            proceeds = shares * sell_price
            commission = proceeds * commission_pct
            cash += proceeds - commission
            pnl_pct = (sell_price / entry_price - 1) * 100
            pnl_abs = (sell_price - entry_price) * shares
            trades.append(
                {
                    "entry_bar": entry_bar,
                    "exit_bar": i,
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(sell_price, 4),
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl_abs": round(pnl_abs, 2),
                    "shares": round(shares, 4),
                    "direction": "long",
                }
            )
            shares = 0.0
            in_position = False
            equity[i] = cash

        # Check entry
        if not in_position and entries[i]:
            buy_price = close[i] * (1 + slippage_pct)
            invest = cash * position_size_pct
            commission = invest * commission_pct
            shares = (invest - commission) / buy_price
            cash -= invest
            entry_price = buy_price
            entry_bar = i
            in_position = True
            equity[i] = cash + shares * close[i]

    # Close open position at end
    if in_position:
        sell_price = close[-1]
        proceeds = shares * sell_price
        commission = proceeds * commission_pct
        cash += proceeds - commission
        pnl_pct = (sell_price / entry_price - 1) * 100
        pnl_abs = (sell_price - entry_price) * shares
        trades.append(
            {
                "entry_bar": entry_bar,
                "exit_bar": n - 1,
                "entry_price": round(entry_price, 4),
                "exit_price": round(sell_price, 4),
                "pnl_pct": round(pnl_pct, 2),
                "pnl_abs": round(pnl_abs, 2),
                "shares": round(shares, 4),
                "direction": "long",
            }
        )
        equity[-1] = cash

    return equity, trades


def run_backtest_sync(
    df: pd.DataFrame,
    strategy: StrategyBase,
    initial_capital: float = 10_000.0,
    commission_pct: float = 0.001,
    slippage_pct: float = 0.0005,
    position_size_pct: float = 0.95,
) -> BacktestResult:
    """Run a backtest on an OHLCV DataFrame. Pure sync — no DB access."""
    # Enrich with indicators — capture the return value; each compute_*() returns a new copy
    df = enrich_dataframe(df)

    # Generate signals
    signals = strategy.generate_signals(df)

    close = df["close"].to_numpy()
    n = len(df)

    # Simulate portfolio
    equity, trades = _simulate_portfolio(
        close=close,
        entries=signals.entries,
        exits=signals.exits,
        initial_capital=initial_capital,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        position_size_pct=position_size_pct,
    )

    # Compute stats
    daily_returns = np.diff(equity) / equity[:-1]
    daily_returns = daily_returns[np.isfinite(daily_returns)]

    total_return_pct = (equity[-1] / initial_capital - 1) * 100
    days = n
    if isinstance(df.index[0], (pd.Timestamp, datetime)):
        days = (df.index[-1] - df.index[0]).days
    cagr_pct = _compute_cagr(initial_capital, equity[-1], days)
    sharpe = _compute_sharpe(daily_returns)
    sortino = _compute_sortino(daily_returns)
    max_dd, max_dd_dur = _compute_max_drawdown(equity)

    # Trade stats
    winning = [t for t in trades if t["pnl_pct"] > 0]
    losing = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = len(winning) / len(trades) * 100 if trades else 0.0
    avg_trade = float(np.mean([t["pnl_pct"] for t in trades])) if trades else 0.0
    avg_win = float(np.mean([t["pnl_pct"] for t in winning])) if winning else 0.0
    avg_loss = float(np.mean([t["pnl_pct"] for t in losing])) if losing else 0.0
    gross_profit = sum(t["pnl_abs"] for t in winning)
    gross_loss = abs(sum(t["pnl_abs"] for t in losing))
    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0 else (999.99 if gross_profit > 0 else 0.0)
    )

    # Equity curve and drawdown as list[dict]
    peak = np.maximum.accumulate(equity)
    drawdown_pct = (equity - peak) / peak * 100

    dates = df.index.tolist()

    def _fmt_date(d: object) -> str:
        if hasattr(d, "strftime"):
            return str(d.strftime("%Y-%m-%d"))  # noqa: strftime narrowed by hasattr
        return str(d)[:10]

    equity_curve = [
        {"date": _fmt_date(dates[i]), "value": round(float(equity[i]), 2)} for i in range(n)
    ]
    drawdown_curve = [
        {"date": _fmt_date(dates[i]), "pct": round(float(drawdown_pct[i]), 2)} for i in range(n)
    ]

    # Add dates to trades
    for t in trades:
        t["entry_date"] = _fmt_date(dates[t["entry_bar"]])
        t["exit_date"] = _fmt_date(dates[t["exit_bar"]])

    # Benchmark: buy and hold
    benchmark_return = (close[-1] / close[0] - 1) * 100
    bh_equity = initial_capital * close / close[0]
    bh_returns = np.diff(bh_equity) / bh_equity[:-1]
    benchmark_sharpe = _compute_sharpe(bh_returns)

    config = BacktestConfig(
        symbol="",
        timeframe="1d",
        start_date=_fmt_date(dates[0]),
        end_date=_fmt_date(dates[-1]),
        strategy_name=strategy.name,
        strategy_params=strategy.parameters,
        initial_capital=initial_capital,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        position_size=position_size_pct,
    )

    return BacktestResult(
        config=config,
        total_return_pct=round(total_return_pct, 2),
        cagr_pct=round(cagr_pct, 2),
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        max_drawdown_pct=round(max_dd, 2),
        max_drawdown_duration_days=max_dd_dur,
        win_rate_pct=round(win_rate, 1),
        profit_factor=round(profit_factor, 2),
        total_trades=len(trades),
        avg_trade_pct=round(avg_trade, 2),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        trades=trades,
        benchmark_return_pct=round(benchmark_return, 2),
        benchmark_sharpe=round(benchmark_sharpe, 4),
    )
