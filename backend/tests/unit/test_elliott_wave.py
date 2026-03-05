"""Unit tests for Elliott Wave detection."""
import pytest
import numpy as np
import pandas as pd
from app.analysis.indicators.elliott_wave import (
    WavePoint, WaveSequence, EWResult,
    _fib_score, _impulse_confidence, _check_impulse_rules,
    _corrective_confidence,
    detect_elliott_waves, compute_ew_signals,
)
from app.analysis.swing_points import detect_swing_points

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


# ── Tests for detect_elliott_waves and compute_ew_signals ─────────────────────

def _make_impulse_df() -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Synthetic bullish impulse: clear 5-wave up structure."""
    raw = [
        100, 120, 150, 180, 200,   # wave 1 up
        190, 175, 155, 138,         # wave 2 down (61.8% retrace)
        170, 200, 240, 280, 310,   # wave 3 up
        295, 270, 248,              # wave 4 down
        270, 300, 330, 350,        # wave 5 up
    ]
    n = len(raw)
    df = pd.DataFrame({
        'time': pd.date_range('2024-01-01', periods=n, freq='D').strftime('%Y-%m-%d'),
        'open': raw,
        'high': [p + 5 for p in raw],
        'low': [p - 5 for p in raw],
        'close': raw,
        'volume': [1_000_000] * n,
    })
    sh_bool, _ = detect_swing_points(df['high'], order=2, atr_filter=0.0)
    _, sl_bool = detect_swing_points(df['low'], order=2, atr_filter=0.0)
    sh_idx = np.where(sh_bool)[0]
    sl_idx = np.where(sl_bool)[0]
    return df, sh_idx, sl_idx


def test_detect_empty_arrays_returns_empty():
    df = pd.DataFrame({'time': ['2024-01-01'] * 5, 'high': [100.0]*5, 'low': [99.0]*5, 'close': [100.0]*5})
    result = detect_elliott_waves(df, np.array([]), np.array([]))
    assert result.best_wave is None
    assert result.confidence == 0.0


def test_detect_too_few_pivots_returns_empty():
    df = pd.DataFrame({
        'time': pd.date_range('2024-01-01', periods=10, freq='D').strftime('%Y-%m-%d'),
        'high': [100.0] * 10,
        'low': [99.0] * 10,
        'close': [100.0] * 10,
    })
    result = detect_elliott_waves(df, np.array([2, 7]), np.array([4]))
    assert result.best_wave is None


def test_detect_impulse_finds_wave_sequence():
    df, sh_idx, sl_idx = _make_impulse_df()
    result = detect_elliott_waves(df, sh_idx, sl_idx)
    assert result.best_wave is not None
    assert result.best_wave.wave_type == 'impulse'
    assert result.best_wave.direction == 'bullish'
    assert len(result.best_wave.waves) == 6
    assert result.best_wave.confidence > 0.0


def test_detect_current_position_is_set():
    df, sh_idx, sl_idx = _make_impulse_df()
    result = detect_elliott_waves(df, sh_idx, sl_idx)
    assert result.current_position is not None


def test_compute_ew_signals_wave3_active():
    wp = [WavePoint('2024-01-01', float(p), str(i), i)
          for i, p in enumerate([100, 200, 138, 310, 248, 350])]
    seq = WaveSequence('impulse', 'bullish', wp, confidence=0.75)
    result = EWResult(best_wave=seq, current_position='wave_3', confidence=0.75)
    sigs = compute_ew_signals(result)
    assert sigs['ew_wave3_active'] == pytest.approx(1.0)
    assert sigs['ew_wave5_active'] == pytest.approx(0.0)
    assert sigs['ew_corrective_abc'] == pytest.approx(0.0)
    assert sigs['ew_ratio_quality'] == pytest.approx(0.75)


def test_compute_ew_signals_wave5():
    wp = [WavePoint('2024-01-01', float(p), str(i), i)
          for i, p in enumerate([100, 200, 138, 310, 248, 350])]
    seq = WaveSequence('impulse', 'bullish', wp, confidence=0.6)
    result = EWResult(best_wave=seq, current_position='wave_5', confidence=0.6)
    sigs = compute_ew_signals(result)
    assert sigs['ew_wave5_active'] == pytest.approx(0.5)
    assert sigs['ew_wave3_active'] == pytest.approx(0.0)


def test_compute_ew_signals_corrective():
    wp = [WavePoint('2024-01-01', float(p), lbl, i)
          for i, (p, lbl) in enumerate([(350, '0'), (200, 'A'), (280, 'B'), (180, 'C')])]
    seq = WaveSequence('corrective', 'bearish', wp, confidence=0.6)
    result = EWResult(best_wave=seq, current_position='wave_C', confidence=0.6)
    sigs = compute_ew_signals(result)
    assert sigs['ew_corrective_abc'] == pytest.approx(-0.3)
    assert sigs['ew_wave3_active'] == pytest.approx(0.0)


def test_compute_ew_signals_no_wave():
    result = EWResult()
    sigs = compute_ew_signals(result)
    assert sigs['ew_wave3_active'] == pytest.approx(0.0)
    assert sigs['ew_wave5_active'] == pytest.approx(0.0)
    assert sigs['ew_corrective_abc'] == pytest.approx(0.0)
    assert sigs['ew_ratio_quality'] == pytest.approx(0.0)
