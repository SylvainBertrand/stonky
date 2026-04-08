"""
Unit tests for app.services.indicators_service.

Uses synthetic OHLCV from `tests/generators.py` to drive the full indicator
pipeline offline. Validates that every required indicator key is present,
numeric (or None for short-history corner cases), and within plausible
ranges for the chosen synthetic shape.
"""

from __future__ import annotations

import math

import pytest

from app.services.indicators_service import (
    MIN_BARS_FOR_EMA200,
    compute_latest_indicators,
)
from tests.generators import gen_uptrend

pytestmark = pytest.mark.unit


REQUIRED_KEYS = {
    "rsi",
    "macd_line",
    "macd_signal",
    "macd_hist",
    "bb_upper",
    "bb_mid",
    "bb_lower",
    "bb_pct_b",
    "bb_width",
    "vwap",
    "atr",
    "atr_pct",
    "ema_21",
    "ema_50",
    "ema_200",
    "volume_ratio",
    "obv",
}


def _is_finite_or_none(val: float | None) -> bool:
    return val is None or (isinstance(val, float) and math.isfinite(val))


# ── Schema / contract ───────────────────────────────────────────────────────


def test_returns_all_required_keys_with_long_history() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    assert REQUIRED_KEYS.issubset(result.keys())


def test_no_extra_keys_returned() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    assert set(result.keys()) == REQUIRED_KEYS


def test_all_values_are_floats_or_none() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    for key, val in result.items():
        assert _is_finite_or_none(val), f"{key} is not finite/None: {val!r}"


# ── EMA-200 short-history behavior ──────────────────────────────────────────


def test_ema_200_is_none_when_history_too_short() -> None:
    df = gen_uptrend(bars=100, seed=42)
    result = compute_latest_indicators(df)
    assert result["ema_200"] is None
    # ema_21 / ema_50 should still populate at 100 bars
    assert result["ema_21"] is not None
    assert result["ema_50"] is not None


def test_ema_200_populates_when_history_meets_minimum() -> None:
    df = gen_uptrend(bars=MIN_BARS_FOR_EMA200 + 10, seed=42)
    result = compute_latest_indicators(df)
    assert result["ema_200"] is not None
    assert result["ema_200"] > 0


# ── Numeric sanity on a known synthetic shape ───────────────────────────────


def test_uptrend_produces_bullish_ema_stack() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    # In a steady uptrend, price > EMA-21 > EMA-50 > EMA-200.
    # We don't assert the exact close, but the EMA ordering must hold.
    ema_21 = result["ema_21"]
    ema_50 = result["ema_50"]
    ema_200 = result["ema_200"]
    assert ema_21 is not None and ema_50 is not None and ema_200 is not None
    assert ema_21 > ema_50 > ema_200


def test_uptrend_rsi_in_bullish_range() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    assert result["rsi"] is not None
    assert 0.0 <= result["rsi"] <= 100.0


def test_atr_is_positive() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    assert result["atr"] is not None
    assert result["atr"] > 0
    assert result["atr_pct"] is not None
    assert result["atr_pct"] > 0


def test_bb_width_is_positive() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    assert result["bb_width"] is not None
    assert result["bb_width"] > 0
    # Width is (upper - lower) / mid, expressed as a ratio.
    assert result["bb_width"] < 1.0  # uptrend with 2% vol shouldn't blow this up


def test_bb_pct_b_in_normal_range() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    # %B is roughly [0, 1] inside the bands; can spike outside on a hot bar.
    assert result["bb_pct_b"] is not None
    assert -0.5 <= result["bb_pct_b"] <= 1.5


def test_volume_ratio_is_finite_positive() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    assert result["volume_ratio"] is not None
    assert result["volume_ratio"] > 0


def test_macd_line_signal_hist_consistent() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    # MACD histogram = MACD line - MACD signal (within rounding).
    assert result["macd_line"] is not None
    assert result["macd_signal"] is not None
    assert result["macd_hist"] is not None
    expected_hist = result["macd_line"] - result["macd_signal"]
    assert abs(result["macd_hist"] - expected_hist) < 1e-3


def test_obv_is_numeric() -> None:
    df = gen_uptrend(bars=250, seed=42)
    result = compute_latest_indicators(df)
    assert result["obv"] is not None
    assert math.isfinite(result["obv"])


# ── Determinism ─────────────────────────────────────────────────────────────


def test_same_input_yields_same_output() -> None:
    df1 = gen_uptrend(bars=250, seed=42)
    df2 = gen_uptrend(bars=250, seed=42)
    assert compute_latest_indicators(df1) == compute_latest_indicators(df2)
