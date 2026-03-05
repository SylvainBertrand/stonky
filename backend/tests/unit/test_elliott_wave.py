"""Unit tests for Elliott Wave detection."""
import pytest
import numpy as np
import pandas as pd
from app.analysis.indicators.elliott_wave import (
    WavePoint, WaveSequence, EWResult,
    _fib_score, _impulse_confidence, _check_impulse_rules,
    _corrective_confidence,
)

pytestmark = pytest.mark.unit


def test_fib_score_exact_match():
    assert _fib_score(0.618, 0.618) == pytest.approx(1.0)


def test_fib_score_at_tolerance_boundary():
    # At exactly tolerance away → score = 0
    score = _fib_score(0.618 * 1.25, 0.618, tolerance=0.25)
    assert score == pytest.approx(0.0, abs=0.01)


def test_fib_score_beyond_tolerance():
    assert _fib_score(0.1, 0.618) == pytest.approx(0.0)


def test_impulse_confidence_perfect_fib():
    # Perfect Fibonacci ratios for bullish: W1 up 100, W2 down 61.8, W3 up 161.8, W4 down 38.2*161.8≈61.8, W5 up 100
    p = [100.0, 200.0, 138.2, 300.0, 238.2, 338.2]
    conf = _impulse_confidence(p)
    assert conf > 0.8  # near-perfect Fibonacci ratios → high confidence


def test_impulse_confidence_terrible_ratios():
    # Completely wrong ratios → low score
    p = [100.0, 200.0, 190.0, 200.0, 195.0, 200.1]
    conf = _impulse_confidence(p)
    assert conf < 0.3


def test_check_impulse_rules_valid_bullish():
    # w0=100, w1=200, w2=138, w3=310, w4=240, w5=350
    prices = [100.0, 200.0, 138.0, 310.0, 240.0, 350.0]
    assert _check_impulse_rules(prices, 'bullish') is True


def test_check_impulse_rules_w2_below_w0():
    # W2 below W0 → invalid
    prices = [100.0, 200.0, 90.0, 310.0, 240.0, 350.0]
    assert _check_impulse_rules(prices, 'bullish') is False


def test_check_impulse_rules_w4_overlaps_w1():
    # W4 below W1 → invalid (overlap)
    prices = [100.0, 200.0, 150.0, 310.0, 180.0, 350.0]
    assert _check_impulse_rules(prices, 'bullish') is False


def test_check_impulse_rules_w3_shortest():
    # W3 is shortest → invalid
    prices = [100.0, 200.0, 160.0, 200.0, 170.0, 350.0]
    assert _check_impulse_rules(prices, 'bullish') is False


def test_check_impulse_rules_valid_bearish():
    prices = [350.0, 240.0, 310.0, 138.0, 200.0, 100.0]
    assert _check_impulse_rules(prices, 'bearish') is True


def test_check_impulse_rules_bearish_w2_above_w0():
    prices = [350.0, 240.0, 360.0, 138.0, 200.0, 100.0]
    assert _check_impulse_rules(prices, 'bearish') is False


def test_corrective_confidence_perfect_fib():
    # B retraces 61.8% of A, C = A
    p = [200.0, 100.0, 161.8, 61.8]
    conf = _corrective_confidence(p)
    assert conf > 0.8  # near-perfect Fibonacci ratios → high confidence


def test_corrective_confidence_zero_amplitude():
    p = [100.0, 100.0, 90.0, 80.0]  # amp_a = 0
    assert _corrective_confidence(p) == 0.0


def test_impulse_confidence_flat_w3():
    # When W3 has zero amplitude, the W4/W3 ratio guard should handle it gracefully
    p = [100.0, 200.0, 138.2, 138.2, 90.0, 190.0]  # W3 is flat (degenerate)
    conf = _impulse_confidence(p)
    assert 0.0 <= conf <= 1.0  # should not raise
