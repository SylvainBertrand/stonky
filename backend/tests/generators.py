"""
Synthetic OHLCV generators for deterministic test fixtures.

Each generator produces a pandas DataFrame with columns:
    time, open, high, low, close, volume

All generators are pure functions with fixed seeds for reproducibility.
The shapes are designed to trigger specific indicator behaviors.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timedelta


def _make_df(
    dates: pd.DatetimeIndex,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
) -> pd.DataFrame:
    """Assemble arrays into a standard OHLCV DataFrame."""
    return pd.DataFrame(
        {
            "time": dates,
            "open": np.round(opens, 4),
            "high": np.round(highs, 4),
            "low": np.round(lows, 4),
            "close": np.round(closes, 4),
            "volume": volumes.astype(int),
        }
    )


def _dates(bars: int, start: str = "2024-01-02") -> pd.DatetimeIndex:
    """Generate business-day date index."""
    return pd.bdate_range(start=start, periods=bars)


def _noise(rng: np.random.Generator, size: int, scale: float) -> np.ndarray:
    return rng.normal(0, scale, size)


def gen_uptrend(
    bars: int = 100,
    seed: int = 42,
    base_price: float = 100.0,
    volatility: float = 0.02,
    drift: float = 0.003,
) -> pd.DataFrame:
    """
    Steady uptrend with random noise.

    Triggers: bullish EMA stack, ADX > 25, Supertrend bullish, RSI 55-70 range.
    """
    rng = np.random.default_rng(seed)
    dates = _dates(bars)

    closes = np.empty(bars)
    closes[0] = base_price
    for i in range(1, bars):
        closes[i] = closes[i - 1] * (1 + drift + _noise(rng, 1, volatility)[0])

    spread = base_price * volatility
    opens = closes + _noise(rng, bars, spread * 0.3)
    highs = np.maximum(opens, closes) + np.abs(_noise(rng, bars, spread * 0.5))
    lows = np.minimum(opens, closes) - np.abs(_noise(rng, bars, spread * 0.5))
    volumes = (rng.lognormal(mean=15, sigma=0.5, size=bars)).astype(int)

    return _make_df(dates, opens, highs, lows, closes, volumes)


def gen_downtrend(
    bars: int = 100,
    seed: int = 42,
    base_price: float = 150.0,
    volatility: float = 0.02,
    drift: float = -0.003,
) -> pd.DataFrame:
    """
    Steady downtrend with random noise.

    Triggers: bearish EMA stack, ADX > 25, Supertrend bearish, RSI 30-45 range.
    """
    rng = np.random.default_rng(seed)
    dates = _dates(bars)

    closes = np.empty(bars)
    closes[0] = base_price
    for i in range(1, bars):
        closes[i] = closes[i - 1] * (1 + drift + _noise(rng, 1, volatility)[0])

    spread = base_price * volatility
    opens = closes + _noise(rng, bars, spread * 0.3)
    highs = np.maximum(opens, closes) + np.abs(_noise(rng, bars, spread * 0.5))
    lows = np.minimum(opens, closes) - np.abs(_noise(rng, bars, spread * 0.5))
    volumes = (rng.lognormal(mean=15, sigma=0.5, size=bars)).astype(int)

    return _make_df(dates, opens, highs, lows, closes, volumes)


def gen_consolidation(
    bars: int = 100,
    seed: int = 42,
    base_price: float = 120.0,
    volatility: float = 0.008,
) -> pd.DataFrame:
    """
    Flat range-bound price action with low volatility.

    Triggers: ADX < 20, Bollinger Bands narrow (squeeze), RSI near 50.
    """
    rng = np.random.default_rng(seed)
    dates = _dates(bars)

    # Mean-reverting process (Ornstein-Uhlenbeck)
    closes = np.empty(bars)
    closes[0] = base_price
    theta = 0.1  # mean reversion speed
    for i in range(1, bars):
        closes[i] = closes[i - 1] + theta * (base_price - closes[i - 1]) + _noise(rng, 1, base_price * volatility)[0]

    spread = base_price * volatility
    opens = closes + _noise(rng, bars, spread * 0.3)
    highs = np.maximum(opens, closes) + np.abs(_noise(rng, bars, spread * 0.4))
    lows = np.minimum(opens, closes) - np.abs(_noise(rng, bars, spread * 0.4))
    volumes = (rng.lognormal(mean=14, sigma=0.3, size=bars)).astype(int)

    return _make_df(dates, opens, highs, lows, closes, volumes)


def gen_v_recovery(
    bars: int = 100,
    seed: int = 42,
    base_price: float = 130.0,
    volatility: float = 0.02,
    drop_pct: float = 0.20,
    drop_start: int = 30,
    drop_duration: int = 15,
    recovery_duration: int = 20,
) -> pd.DataFrame:
    """
    Sharp drop followed by sharp recovery.

    Triggers: RSI oversold then divergence, bullish engulfing at bottom,
    OBV divergence, MACD bullish crossover during recovery.
    """
    rng = np.random.default_rng(seed)
    dates = _dates(bars)

    closes = np.empty(bars)
    closes[0] = base_price

    # Pre-drop: gentle uptrend
    for i in range(1, drop_start):
        closes[i] = closes[i - 1] * (1 + 0.001 + _noise(rng, 1, volatility * 0.5)[0])

    # Drop phase
    drop_per_bar = drop_pct / drop_duration
    for i in range(drop_start, min(drop_start + drop_duration, bars)):
        closes[i] = closes[i - 1] * (1 - drop_per_bar + _noise(rng, 1, volatility * 0.3)[0])

    # Recovery phase
    bottom = closes[min(drop_start + drop_duration - 1, bars - 1)]
    target = base_price * (1 + 0.05)  # recover above starting price
    recovery_end = min(drop_start + drop_duration + recovery_duration, bars)
    if drop_start + drop_duration < bars:
        recovery_per_bar = (target - bottom) / recovery_duration
        for i in range(drop_start + drop_duration, recovery_end):
            closes[i] = closes[i - 1] + recovery_per_bar + _noise(rng, 1, base_price * volatility * 0.5)[0]

    # Post-recovery: gentle drift
    for i in range(recovery_end, bars):
        closes[i] = closes[i - 1] * (1 + 0.001 + _noise(rng, 1, volatility * 0.5)[0])

    spread = base_price * volatility
    opens = closes + _noise(rng, bars, spread * 0.3)
    # Exaggerate high/low during drop for realistic wicks
    hl_multiplier = np.ones(bars)
    hl_multiplier[drop_start : drop_start + drop_duration] = 2.0
    highs = np.maximum(opens, closes) + np.abs(_noise(rng, bars, spread * 0.5)) * hl_multiplier
    lows = np.minimum(opens, closes) - np.abs(_noise(rng, bars, spread * 0.5)) * hl_multiplier

    # Volume spike during drop and early recovery
    volumes = rng.lognormal(mean=14.5, sigma=0.4, size=bars)
    volumes[drop_start : drop_start + drop_duration] *= 3.0
    volumes[drop_start + drop_duration : recovery_end] *= 2.0
    volumes = volumes.astype(int)

    return _make_df(dates, opens, highs, lows, closes, volumes)


def gen_breakout(
    bars: int = 100,
    seed: int = 42,
    base_price: float = 110.0,
    volatility: float = 0.008,
    breakout_bar: int = 60,
    breakout_volatility: float = 0.025,
) -> pd.DataFrame:
    """
    Consolidation phase followed by breakout expansion.

    Triggers: TTM Squeeze fire at breakout_bar, Bollinger Band expansion,
    ADX rising from <20 to >25, volume spike, MACD histogram turning positive.
    """
    rng = np.random.default_rng(seed)
    dates = _dates(bars)

    closes = np.empty(bars)
    closes[0] = base_price

    # Consolidation phase (mean-reverting, tight range)
    theta = 0.1
    for i in range(1, breakout_bar):
        closes[i] = closes[i - 1] + theta * (base_price - closes[i - 1]) + _noise(rng, 1, base_price * volatility)[0]

    # Breakout + trend
    for i in range(breakout_bar, bars):
        drift = 0.005 * (1 - 0.5 * (i - breakout_bar) / (bars - breakout_bar))  # decaying drift
        closes[i] = closes[i - 1] * (1 + drift + _noise(rng, 1, breakout_volatility)[0])

    spread_pre = base_price * volatility
    spread_post = base_price * breakout_volatility
    spreads = np.where(np.arange(bars) < breakout_bar, spread_pre, spread_post)

    opens = closes + _noise(rng, bars, spreads * 0.3)
    highs = np.maximum(opens, closes) + np.abs(_noise(rng, bars, spreads * 0.5))
    lows = np.minimum(opens, closes) - np.abs(_noise(rng, bars, spreads * 0.5))

    volumes = rng.lognormal(mean=14.5, sigma=0.4, size=bars)
    volumes[breakout_bar : breakout_bar + 10] *= 3.0  # volume spike at breakout
    volumes = volumes.astype(int)

    return _make_df(dates, opens, highs, lows, closes, volumes)


def gen_harmonic_gartley(
    seed: int = 42,
    base_price: float = 100.0,
    volatility: float = 0.005,
    bars_per_leg: int = 15,
) -> pd.DataFrame:
    """
    Synthetic bullish Gartley XABCD pattern with ideal Fibonacci ratios.

    X=100, A=120 (XA leg up), B=107.64 (61.8% ret), C=115.28 (88.6% of AB),
    D=104.28 (78.6% of XA = potential reversal zone).

    Triggers: pyharmonics Gartley detection, RSI oversold at D, Fib levels.
    """
    rng = np.random.default_rng(seed)

    # Ideal Gartley ratios
    x_price = base_price
    a_price = base_price * 1.20  # XA leg: +20%
    xa_range = a_price - x_price
    b_price = a_price - xa_range * 0.618  # B retraces 61.8% of XA
    ab_range = a_price - b_price
    c_price = b_price + ab_range * 0.886  # C retraces 88.6% of AB
    d_price = x_price + xa_range * (1 - 0.786)  # D at 78.6% retracement of XA

    # Build price path through XABCD
    legs = [
        np.linspace(x_price, a_price, bars_per_leg),  # X → A
        np.linspace(a_price, b_price, bars_per_leg),  # A → B
        np.linspace(b_price, c_price, bars_per_leg),  # B → C
        np.linspace(c_price, d_price, bars_per_leg),  # C → D
        np.linspace(d_price, d_price * 1.08, bars_per_leg),  # D → recovery
    ]
    closes_raw = np.concatenate(legs)
    bars = len(closes_raw)

    # Add noise
    closes = closes_raw + _noise(rng, bars, base_price * volatility)
    dates = _dates(bars)

    spread = base_price * volatility * 2
    opens = closes + _noise(rng, bars, spread * 0.3)
    highs = np.maximum(opens, closes) + np.abs(_noise(rng, bars, spread * 0.5))
    lows = np.minimum(opens, closes) - np.abs(_noise(rng, bars, spread * 0.5))

    # Volume: higher at reversal points (A, B, C, D)
    volumes = rng.lognormal(mean=14.5, sigma=0.3, size=bars)
    for pivot_bar in [bars_per_leg, 2 * bars_per_leg, 3 * bars_per_leg, 4 * bars_per_leg]:
        if pivot_bar < bars:
            start = max(0, pivot_bar - 2)
            end = min(bars, pivot_bar + 3)
            volumes[start:end] *= 2.0
    volumes = volumes.astype(int)

    return _make_df(dates, opens, highs, lows, closes, volumes)


def gen_double_top(
    bars: int = 100,
    seed: int = 42,
    base_price: float = 100.0,
    peak_price: float = 125.0,
    volatility: float = 0.01,
) -> pd.DataFrame:
    """
    Two peaks at approximately the same level with a valley between.

    Triggers: chart pattern detection (double top), RSI bearish divergence
    (second peak with lower RSI), potential MACD divergence.
    """
    rng = np.random.default_rng(seed)
    dates = _dates(bars)

    # Build path: rise → peak1 → pullback → peak2 → decline
    q = bars // 5
    segments = [
        np.linspace(base_price, peak_price, q),              # rise to peak 1
        np.linspace(peak_price, base_price * 1.08, q),       # pullback to neckline
        np.linspace(base_price * 1.08, peak_price * 0.995, q),  # rise to peak 2 (slightly lower)
        np.linspace(peak_price * 0.995, base_price * 1.02, q),  # decline
        np.linspace(base_price * 1.02, base_price * 0.92, bars - 4 * q),  # breakdown
    ]
    closes_raw = np.concatenate(segments)
    closes = closes_raw + _noise(rng, bars, base_price * volatility)

    spread = base_price * volatility * 2
    opens = closes + _noise(rng, bars, spread * 0.3)
    highs = np.maximum(opens, closes) + np.abs(_noise(rng, bars, spread * 0.5))
    lows = np.minimum(opens, closes) - np.abs(_noise(rng, bars, spread * 0.5))

    # Volume: declining on second peak (classic divergence)
    volumes = rng.lognormal(mean=15, sigma=0.4, size=bars)
    volumes[q - 3 : q + 3] *= 2.5       # high volume at peak 1
    volumes[3 * q - 3 : 3 * q + 3] *= 1.5  # lower volume at peak 2
    volumes = volumes.astype(int)

    return _make_df(dates, opens, highs, lows, closes, volumes)


def gen_bullish_engulfing(
    bars: int = 50,
    seed: int = 42,
    base_price: float = 100.0,
    volatility: float = 0.015,
) -> pd.DataFrame:
    """
    Downtrend ending with a textbook bullish engulfing candle at bar -2.

    Triggers: ta-lib CDL_ENGULFING, candlestick pattern detection.
    The second-to-last candle is a small bearish body. The last candle
    opens below the prior low and closes above the prior open.
    """
    rng = np.random.default_rng(seed)
    dates = _dates(bars)

    # Downtrend for most of the series
    closes = np.empty(bars)
    closes[0] = base_price
    for i in range(1, bars - 2):
        closes[i] = closes[i - 1] * (1 - 0.003 + _noise(rng, 1, volatility)[0])

    # Second-to-last bar: small bearish candle
    prior_close = closes[bars - 3]
    small_body = prior_close * 0.005
    closes[bars - 2] = prior_close - small_body  # small red body

    # Last bar: bullish engulfing
    engulfing_open = closes[bars - 2] - prior_close * 0.003  # open below prior close
    engulfing_close = prior_close + small_body * 3  # close above prior open
    closes[bars - 1] = engulfing_close

    spread = base_price * volatility
    opens = closes + _noise(rng, bars, spread * 0.2)

    # Fix the engulfing candles specifically
    opens[bars - 2] = prior_close  # prior bar opens at previous close
    opens[bars - 1] = engulfing_open

    highs = np.maximum(opens, closes) + np.abs(_noise(rng, bars, spread * 0.3))
    lows = np.minimum(opens, closes) - np.abs(_noise(rng, bars, spread * 0.3))

    # Ensure engulfing candle's body fully contains prior candle's body
    lows[bars - 1] = min(lows[bars - 1], engulfing_open - spread * 0.1)
    highs[bars - 1] = max(highs[bars - 1], engulfing_close + spread * 0.1)

    volumes = rng.lognormal(mean=14.5, sigma=0.4, size=bars)
    volumes[bars - 1] *= 2.5  # volume spike on engulfing candle
    volumes = volumes.astype(int)

    return _make_df(dates, opens, highs, lows, closes, volumes)
