"""YOLO pattern-triggered backtest strategy."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.strategies.base import SignalResult


@dataclass
class YOLOPatternStrategy:
    """Entry on YOLO-detected chart pattern, exit via ATR trailing stop or target."""

    pattern_names: list[str] = field(default_factory=lambda: ["bull_flag", "ascending_triangle"])
    min_confidence: float = 0.7
    name: str = field(init=False, default="yolo_pattern")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "min_confidence": [0.6, 0.7, 0.8],
            "pattern_names": [
                ["bull_flag"],
                ["ascending_triangle"],
                ["bull_flag", "ascending_triangle"],
            ],
        },
    )

    @property
    def parameters(self) -> dict:
        return {
            "pattern_names": self.pattern_names,
            "min_confidence": self.min_confidence,
        }

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)
        stop_prices = np.full(n, np.nan)
        target_prices = np.full(n, np.nan)

        if "yolo_pattern" not in df.columns:
            return SignalResult(entries=entries, exits=exits)

        close = df["close"].to_numpy()
        atr = df["atr"].to_numpy()

        for i in range(n - 1):
            pattern = df.iloc[i]["yolo_pattern"]
            confidence = df.iloc[i]["yolo_confidence"]

            if pattern is None or pd.isna(confidence):
                continue
            if pattern not in self.pattern_names:
                continue
            if confidence < self.min_confidence:
                continue

            # Enter on next bar
            entries[i + 1] = True
            if not np.isnan(atr[i + 1]):
                stop_prices[i + 1] = close[i + 1] - 2.0 * atr[i + 1]
            else:
                stop_prices[i + 1] = close[i + 1] * 0.95
            # Target: 1.5x pattern height approximation
            if i >= 10:
                target_prices[i + 1] = close[i + 1] + 1.5 * abs(close[i] - close[max(0, i - 10)])
            else:
                target_prices[i + 1] = close[i + 1] * 1.05

        return SignalResult(
            entries=entries,
            exits=exits,
            stop_prices=stop_prices if entries.any() else None,
            target_prices=target_prices if entries.any() else None,
        )

    def describe(self) -> str:
        return f"YOLO Pattern ({', '.join(self.pattern_names)}, conf>{self.min_confidence})"
