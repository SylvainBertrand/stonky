"""Custom rule-combiner strategy configured via JSON from the UI."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.strategies.base import SignalResult

# Map UI indicator names to DataFrame column names
INDICATOR_MAP: dict[str, str] = {
    "rsi": "rsi_14",
    "macd_hist": "macdh",
    "adx": "adx",
    "stoch_k": "stoch_k",
    "supertrend": "supertrend_dir",
    "ema21_slope": "_ema21_slope",
    "obv_slope": "_obv_slope",
    "cmf": "cmf",
    "bb_pct": "bbp",
    "squeeze_on": "squeeze_on",
    "squeeze_fired": "squeeze_fired",
}

# Supertrend string values mapped to numeric
SUPERTREND_VALUES = {"bullish": 1, "bearish": -1}


def _get_series(df: pd.DataFrame, indicator: str) -> np.ndarray:
    """Get the numpy array for an indicator, computing derived columns if needed."""
    if indicator == "ema21_slope":
        if "_ema21_slope" not in df.columns:
            df["_ema21_slope"] = df["ema_21"].diff()
        return df["_ema21_slope"].to_numpy()
    if indicator == "obv_slope":
        if "_obv_slope" not in df.columns:
            df["_obv_slope"] = df["obv"].diff()
        return df["_obv_slope"].to_numpy()

    col = INDICATOR_MAP.get(indicator, indicator)
    return df[col].to_numpy()


def _eval_rule(
    series: np.ndarray,
    operator: str,
    value: object,
    prev_series: np.ndarray | None = None,
) -> np.ndarray:
    """Evaluate a single rule, returning a boolean array. No eval() — safe dispatch."""
    # Handle supertrend string values
    if isinstance(value, str) and value in SUPERTREND_VALUES:
        value = SUPERTREND_VALUES[value]

    if operator == "<":
        return series < value
    elif operator == ">":
        return series > value
    elif operator == "<=":
        return series <= value
    elif operator == ">=":
        return series >= value
    elif operator == "==":
        if isinstance(value, bool):
            return series.astype(bool) == value
        return series == value
    elif operator == "crosses_above":
        if prev_series is None:
            return np.zeros(len(series), dtype=bool)
        result = np.zeros(len(series), dtype=bool)
        result[1:] = (series[1:] > value) & (prev_series[1:] <= value)
        return result
    elif operator == "crosses_below":
        if prev_series is None:
            return np.zeros(len(series), dtype=bool)
        result = np.zeros(len(series), dtype=bool)
        result[1:] = (series[1:] < value) & (prev_series[1:] >= value)
        return result
    else:
        raise ValueError(f"Unknown operator: {operator}")


@dataclass
class CustomStrategy:
    """Flexible rule combiner configured via JSON dict from the UI."""

    config: dict
    name: str = field(init=False, default="custom")
    param_space: dict = field(init=False, default_factory=dict)

    @property
    def parameters(self) -> dict:
        return self.config

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entry_rules = self.config.get("entry_rules", [])
        exit_rules = self.config.get("exit_rules", [])
        rule_logic = self.config.get("rule_logic", "AND")
        stop_type = self.config.get("stop_type", "atr")
        stop_value = self.config.get("stop_value", 1.5)
        target_type = self.config.get("target_type")
        target_value = self.config.get("target_value", 2.0)

        # Evaluate entry rules
        entry_masks = []
        for rule in entry_rules:
            series = _get_series(df, rule["indicator"])
            prev_series = np.roll(series, 1)
            mask = _eval_rule(series, rule["operator"], rule["value"], prev_series)
            entry_masks.append(mask)

        if entry_masks:
            if rule_logic == "AND":
                entries = np.all(entry_masks, axis=0)
            else:  # OR
                entries = np.any(entry_masks, axis=0)
        else:
            entries = np.zeros(n, dtype=bool)

        # Evaluate exit rules (any exit rule triggers exit)
        exit_masks = []
        for rule in exit_rules:
            series = _get_series(df, rule["indicator"])
            prev_series = np.roll(series, 1)
            mask = _eval_rule(series, rule["operator"], rule["value"], prev_series)
            exit_masks.append(mask)

        if exit_masks:
            exits = np.any(exit_masks, axis=0)
        else:
            exits = np.zeros(n, dtype=bool)

        # Compute stops
        stop_prices = None
        if stop_type == "atr" and "atr" in df.columns:
            stop_prices = df["close"].to_numpy() - stop_value * df["atr"].to_numpy()
        elif stop_type == "fixed_pct":
            stop_prices = df["close"].to_numpy() * (1 - stop_value / 100)

        # Compute targets
        target_prices = None
        if target_type == "rr" and stop_prices is not None:
            close = df["close"].to_numpy()
            risk = close - stop_prices
            target_prices = close + target_value * risk
        elif target_type == "fib_extension" and "atr" in df.columns:
            target_prices = df["close"].to_numpy() + target_value * df["atr"].to_numpy()

        # Don't allow entry and exit on same bar
        both = entries & exits
        exits[both] = False

        return SignalResult(
            entries=entries.astype(bool),
            exits=exits.astype(bool),
            stop_prices=stop_prices,
            target_prices=target_prices,
        )

    def describe(self) -> str:
        n_entry = len(self.config.get("entry_rules", []))
        n_exit = len(self.config.get("exit_rules", []))
        logic = self.config.get("rule_logic", "AND")
        return f"Custom ({n_entry} entry rules [{logic}], {n_exit} exit rules)"
