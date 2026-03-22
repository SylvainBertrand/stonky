"""Strategy protocol and signal result dataclass for backtesting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd


@dataclass
class SignalResult:
    """Output of a strategy's signal generation."""

    entries: np.ndarray  # bool array, True = enter long
    exits: np.ndarray  # bool array, True = exit long
    stop_prices: np.ndarray | None = None  # per-bar absolute stop price
    target_prices: np.ndarray | None = None  # per-bar absolute target price


class StrategyBase(Protocol):
    """Protocol that all backtest strategies must satisfy."""

    name: str
    parameters: dict
    param_space: dict  # {param_name: [possible_values]} for sweep

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        """Given OHLCV+indicators DataFrame, return entry/exit arrays (same length as df)."""
        ...

    def describe(self) -> str:
        """Human-readable description of current parameter config."""
        ...
