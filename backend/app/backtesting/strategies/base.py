"""Strategy protocol and signal result dataclass for backtesting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import pandas as pd


@dataclass
class SignalResult:
    """Output of a strategy's signal generation."""

    entries: np.ndarray[Any, np.dtype[Any]]  # bool array, True = enter long
    exits: np.ndarray[Any, np.dtype[Any]]  # bool array, True = exit long
    stop_prices: np.ndarray[Any, np.dtype[Any]] | None = None  # per-bar absolute stop price
    target_prices: np.ndarray[Any, np.dtype[Any]] | None = None  # per-bar absolute target price


class StrategyBase(Protocol):
    """Protocol that all backtest strategies must satisfy."""

    name: str
    parameters: dict[str, Any]
    param_space: dict[str, Any]  # {param_name: [possible_values]} for sweep

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        """Given OHLCV+indicators DataFrame, return entry/exit arrays (same length as df)."""
        ...

    def describe(self) -> str:
        """Human-readable description of current parameter config."""
        ...
