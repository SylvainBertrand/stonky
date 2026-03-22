"""Indicator-based backtest strategies for baseline comparison."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.strategies.base import SignalResult


@dataclass
class EMACrossoverStrategy:
    """Entry when fast EMA crosses above slow EMA; exit on cross below."""

    fast: int = 21
    slow: int = 50
    name: str = field(init=False, default="ema_crossover")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {"fast": [9, 12, 21], "slow": [26, 50, 100]},
    )

    @property
    def parameters(self) -> dict:
        return {"fast": self.fast, "slow": self.slow}

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        fast_col = f"ema_{self.fast}"
        slow_col = f"ema_{self.slow}"

        # If non-standard EMA periods requested, compute them
        if fast_col not in df.columns:
            df[fast_col] = df["close"].ewm(span=self.fast, adjust=False).mean()
        if slow_col not in df.columns:
            df[slow_col] = df["close"].ewm(span=self.slow, adjust=False).mean()

        fast_ema = df[fast_col].to_numpy()
        slow_ema = df[slow_col].to_numpy()

        # Cross above: fast was <= slow, now fast > slow
        cross_above = (fast_ema[1:] > slow_ema[1:]) & (
            np.roll(fast_ema, 1)[1:] <= np.roll(slow_ema, 1)[1:]
        )
        # Cross below: fast was >= slow, now fast < slow
        cross_below = (fast_ema[1:] < slow_ema[1:]) & (
            np.roll(fast_ema, 1)[1:] >= np.roll(slow_ema, 1)[1:]
        )

        entries = np.zeros(len(df), dtype=bool)
        exits = np.zeros(len(df), dtype=bool)
        entries[1:] = cross_above
        exits[1:] = cross_below

        return SignalResult(entries=entries, exits=exits)

    def describe(self) -> str:
        return f"EMA Crossover ({self.fast}/{self.slow})"


@dataclass
class RSIThresholdStrategy:
    """Entry when RSI crosses above oversold; exit when RSI crosses above overbought."""

    oversold: int = 30
    overbought: int = 70
    name: str = field(init=False, default="rsi_threshold")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {"oversold": [25, 30, 35], "overbought": [65, 70, 75]},
    )

    @property
    def parameters(self) -> dict:
        return {"oversold": self.oversold, "overbought": self.overbought}

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        rsi = df["rsi_14"].to_numpy()
        prev_rsi = np.roll(rsi, 1)

        entries = np.zeros(len(df), dtype=bool)
        exits = np.zeros(len(df), dtype=bool)

        # Cross above oversold
        entries[1:] = (rsi[1:] > self.oversold) & (prev_rsi[1:] <= self.oversold)
        # Cross above overbought
        exits[1:] = (rsi[1:] > self.overbought) & (prev_rsi[1:] <= self.overbought)

        return SignalResult(entries=entries, exits=exits)

    def describe(self) -> str:
        return f"RSI Threshold (oversold={self.oversold}, overbought={self.overbought})"


@dataclass
class MACDCrossStrategy:
    """Entry when MACD crosses above signal; exit on cross below."""

    fast: int = 12
    slow: int = 26
    signal: int = 9
    name: str = field(init=False, default="macd_cross")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "fast": [8, 12, 16],
            "slow": [21, 26, 30],
            "signal": [7, 9, 11],
        },
    )

    @property
    def parameters(self) -> dict:
        return {"fast": self.fast, "slow": self.slow, "signal": self.signal}

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        # Use pre-computed macd/macds if default params, otherwise recompute
        if self.fast == 12 and self.slow == 26 and self.signal == 9:
            macd_line = df["macd"].to_numpy()
            signal_line = df["macds"].to_numpy()
        else:
            fast_ema = df["close"].ewm(span=self.fast, adjust=False).mean()
            slow_ema = df["close"].ewm(span=self.slow, adjust=False).mean()
            macd_line = (fast_ema - slow_ema).to_numpy()
            signal_line = pd.Series(macd_line).ewm(span=self.signal, adjust=False).mean().to_numpy()

        prev_macd = np.roll(macd_line, 1)
        prev_signal = np.roll(signal_line, 1)

        entries = np.zeros(len(df), dtype=bool)
        exits = np.zeros(len(df), dtype=bool)

        entries[1:] = (macd_line[1:] > signal_line[1:]) & (prev_macd[1:] <= prev_signal[1:])
        exits[1:] = (macd_line[1:] < signal_line[1:]) & (prev_macd[1:] >= prev_signal[1:])

        return SignalResult(entries=entries, exits=exits)

    def describe(self) -> str:
        return f"MACD Cross ({self.fast}/{self.slow}/{self.signal})"


@dataclass
class SupertrendStrategy:
    """Entry when price crosses above Supertrend; exit on cross below."""

    atr_period: int = 10
    multiplier: float = 3.0
    name: str = field(init=False, default="supertrend")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "atr_period": [7, 10, 14],
            "multiplier": [2.0, 2.5, 3.0, 3.5],
        },
    )

    @property
    def parameters(self) -> dict:
        return {"atr_period": self.atr_period, "multiplier": self.multiplier}

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        # Use pre-computed supertrend_dir (default params: period=10, mult=3.0)
        st_dir = df["supertrend_dir"].to_numpy()
        prev_dir = np.roll(st_dir, 1)

        entries = np.zeros(len(df), dtype=bool)
        exits = np.zeros(len(df), dtype=bool)

        # Bullish flip: dir changes to +1
        entries[1:] = (st_dir[1:] == 1) & (prev_dir[1:] == -1)
        # Bearish flip: dir changes to -1
        exits[1:] = (st_dir[1:] == -1) & (prev_dir[1:] == 1)

        return SignalResult(entries=entries, exits=exits)

    def describe(self) -> str:
        return f"Supertrend (ATR={self.atr_period}, mult={self.multiplier})"
