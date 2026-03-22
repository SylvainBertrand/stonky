"""Profile-based backtest strategies mirroring scanner profiles."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.strategies.base import SignalResult


@dataclass
class MomentumBreakoutStrategy:
    """TTM Squeeze fires + ADX + RSI zone + volume surge."""

    rsi_min: int = 50
    rsi_max: int = 70
    adx_min: int = 20
    volume_multiplier: float = 1.5
    squeeze_required: bool = True
    name: str = field(init=False, default="momentum_breakout")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "rsi_min": [45, 50, 55],
            "rsi_max": [65, 70, 75],
            "adx_min": [15, 20, 25],
            "volume_multiplier": [1.2, 1.5, 2.0],
        },
    )

    @property
    def parameters(self) -> dict:
        return {
            "rsi_min": self.rsi_min,
            "rsi_max": self.rsi_max,
            "adx_min": self.adx_min,
            "volume_multiplier": self.volume_multiplier,
            "squeeze_required": self.squeeze_required,
        }

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)
        stop_prices = np.full(n, np.nan)

        rsi = df["rsi_14"].to_numpy()
        adx = df["adx"].to_numpy()
        volume = df["volume"].to_numpy().astype(float)
        close = df["close"].to_numpy()
        atr = df["atr"].to_numpy()
        st_dir = df["supertrend_dir"].to_numpy()

        # 20-bar average volume
        vol_avg = pd.Series(volume).rolling(20).mean().to_numpy()

        squeeze_fired = (
            df["squeeze_fired"].to_numpy().astype(bool)
            if "squeeze_fired" in df.columns
            else np.ones(n, dtype=bool)
        )

        for i in range(1, n):
            rsi_ok = self.rsi_min <= rsi[i] <= self.rsi_max
            adx_ok = adx[i] > self.adx_min
            vol_ok = not np.isnan(vol_avg[i]) and volume[i] > self.volume_multiplier * vol_avg[i]
            squeeze_ok = (not self.squeeze_required) or squeeze_fired[i]

            if rsi_ok and adx_ok and vol_ok and squeeze_ok:
                entries[i] = True
                stop_prices[i] = close[i] - 1.5 * atr[i]

            # Exit: RSI > 75 OR Supertrend bearish flip
            if rsi[i] > 75:
                exits[i] = True
            if st_dir[i] == -1 and st_dir[i - 1] == 1:
                exits[i] = True

        return SignalResult(
            entries=entries,
            exits=exits,
            stop_prices=stop_prices if entries.any() else None,
        )

    def describe(self) -> str:
        return f"Momentum Breakout (RSI {self.rsi_min}-{self.rsi_max}, ADX>{self.adx_min})"


@dataclass
class TrendFollowingStrategy:
    """EMA stack + ADX + RSI pullback entry."""

    adx_min: int = 25
    ema_stack_required: bool = True
    rsi_pullback_min: int = 40
    rsi_pullback_max: int = 50
    name: str = field(init=False, default="trend_following")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "adx_min": [20, 25, 30],
            "rsi_pullback_min": [35, 40, 45],
            "rsi_pullback_max": [50, 55, 60],
        },
    )

    @property
    def parameters(self) -> dict:
        return {
            "adx_min": self.adx_min,
            "ema_stack_required": self.ema_stack_required,
            "rsi_pullback_min": self.rsi_pullback_min,
            "rsi_pullback_max": self.rsi_pullback_max,
        }

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)

        ema21 = df["ema_21"].to_numpy()
        ema50 = df["ema_50"].to_numpy()
        ema200 = df["ema_200"].to_numpy()
        adx = df["adx"].to_numpy()
        rsi = df["rsi_14"].to_numpy()
        st_dir = df["supertrend_dir"].to_numpy()

        for i in range(1, n):
            # EMA stack: 21 > 50 > 200
            stack_ok = (not self.ema_stack_required) or (ema21[i] > ema50[i] > ema200[i])
            adx_ok = adx[i] > self.adx_min
            pullback_ok = self.rsi_pullback_min <= rsi[i] <= self.rsi_pullback_max

            if stack_ok and adx_ok and pullback_ok:
                entries[i] = True

            # Exit: EMA 21 crosses below EMA 50 OR Supertrend bearish
            if ema21[i] < ema50[i] and ema21[i - 1] >= ema50[i - 1]:
                exits[i] = True
            if st_dir[i] == -1 and st_dir[i - 1] == 1:
                exits[i] = True

        return SignalResult(entries=entries, exits=exits)

    def describe(self) -> str:
        return (
            f"Trend Following (ADX>{self.adx_min}, "
            f"pullback RSI {self.rsi_pullback_min}-{self.rsi_pullback_max})"
        )


@dataclass
class MeanReversionStrategy:
    """Oversold RSI + Stoch + BB touch + CMF confirmation."""

    rsi_max: int = 30
    stoch_k_max: int = 20
    require_bb_touch: bool = True
    require_cmf_positive: bool = True
    name: str = field(init=False, default="mean_reversion")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "rsi_max": [25, 30, 35],
            "stoch_k_max": [15, 20, 25],
        },
    )

    @property
    def parameters(self) -> dict:
        return {
            "rsi_max": self.rsi_max,
            "stoch_k_max": self.stoch_k_max,
            "require_bb_touch": self.require_bb_touch,
            "require_cmf_positive": self.require_cmf_positive,
        }

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)
        stop_prices = np.full(n, np.nan)

        rsi = df["rsi_14"].to_numpy()
        stoch_k = df["stoch_k"].to_numpy()
        close = df["close"].to_numpy()
        low = df["low"].to_numpy()
        bbl = df["bbl"].to_numpy()
        bbm = df["bbm"].to_numpy()
        cmf = df["cmf"].to_numpy()

        for i in range(1, n):
            rsi_ok = rsi[i] < self.rsi_max
            stoch_ok = stoch_k[i] < self.stoch_k_max
            bb_ok = (not self.require_bb_touch) or (close[i] <= bbl[i])
            cmf_ok = (not self.require_cmf_positive) or (cmf[i] > 0 and cmf[i - 1] <= 0)

            if rsi_ok and stoch_ok and bb_ok and cmf_ok:
                entries[i] = True
                # Stop below recent 10-bar swing low
                lookback = max(0, i - 10)
                stop_prices[i] = np.nanmin(low[lookback : i + 1]) * 0.99

            # Exit: RSI > 55 OR price reaches BB midline
            if rsi[i] > 55:
                exits[i] = True
            if not np.isnan(bbm[i]) and close[i] >= bbm[i] and close[i - 1] < bbm[i - 1]:
                exits[i] = True

        return SignalResult(
            entries=entries,
            exits=exits,
            stop_prices=stop_prices if entries.any() else None,
        )

    def describe(self) -> str:
        return f"Mean Reversion (RSI<{self.rsi_max}, Stoch<{self.stoch_k_max})"


@dataclass
class HarmonicSetupStrategy:
    """Entry on completed harmonic pattern with RSI divergence confirmation."""

    min_pattern_score: float = 0.6
    require_rsi_divergence: bool = True
    name: str = field(init=False, default="harmonic_setup")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {"min_pattern_score": [0.5, 0.6, 0.7, 0.8]},
    )

    @property
    def parameters(self) -> dict:
        return {
            "min_pattern_score": self.min_pattern_score,
            "require_rsi_divergence": self.require_rsi_divergence,
        }

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)
        stop_prices = np.full(n, np.nan)
        target_prices = np.full(n, np.nan)

        # Harmonic columns are materialized by the runner
        has_harmonics = "harmonic_detected" in df.columns
        if not has_harmonics:
            return SignalResult(entries=entries, exits=exits)

        detected = df["harmonic_detected"].to_numpy().astype(bool)
        score = df["harmonic_score"].to_numpy()
        prz_low = df["harmonic_prz_low"].to_numpy()
        prz_high = df["harmonic_prz_high"].to_numpy()
        x_price = df["harmonic_x_price"].to_numpy()
        close = df["close"].to_numpy()
        rsi = df["rsi_14"].to_numpy()

        for i in range(1, n):
            if not detected[i]:
                continue
            if score[i] < self.min_pattern_score:
                continue
            # RSI divergence proxy: check if RSI is oversold
            if self.require_rsi_divergence and rsi[i] > 40:
                continue

            entries[i] = True
            stop_prices[i] = x_price[i]  # Stop beyond X point
            # Target: 61.8% extension above PRZ
            prz_range = prz_high[i] - prz_low[i]
            target_prices[i] = prz_high[i] + 0.618 * prz_range

        # Exit when price drops below PRZ low
        for i in range(1, n):
            if has_harmonics and detected[i] and close[i] < prz_low[i]:
                exits[i] = True

        return SignalResult(
            entries=entries,
            exits=exits,
            stop_prices=stop_prices if entries.any() else None,
            target_prices=target_prices if entries.any() else None,
        )

    def describe(self) -> str:
        div = "required" if self.require_rsi_divergence else "optional"
        return f"Harmonic Setup (score>{self.min_pattern_score}, div={div})"
