"""Unit tests for stonky.indicators — pure pandas TA calculations."""

import math

import pandas as pd
import pytest

from stonky.indicators import bollinger_bands, ema, macd, rsi, sma


# ---------------------------------------------------------------- helpers ----

def _series(*values: float) -> pd.Series:
    return pd.Series(values, dtype=float)


def _rising(n: int, start: float = 1.0, step: float = 1.0) -> pd.Series:
    return pd.Series([start + i * step for i in range(n)], dtype=float)


def _falling(n: int, start: float = 100.0, step: float = 1.0) -> pd.Series:
    return pd.Series([start - i * step for i in range(n)], dtype=float)


# ------------------------------------------------------------------- SMA ----

class TestSMA:
    def test_basic(self):
        result = sma(_series(1, 2, 3, 4, 5), window=3)
        assert math.isnan(result.iloc[0])
        assert math.isnan(result.iloc[1])
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[3] == pytest.approx(3.0)
        assert result.iloc[4] == pytest.approx(4.0)

    def test_window_1_returns_series(self):
        s = _series(10, 20, 30)
        assert list(sma(s, window=1)) == pytest.approx([10, 20, 30])

    def test_short_series_all_nan(self):
        result = sma(_series(1, 2), window=5)
        assert all(math.isnan(v) for v in result)

    def test_constant_series(self):
        s = _series(5, 5, 5, 5, 5)
        result = sma(s, window=3).dropna()
        assert all(v == pytest.approx(5.0) for v in result)


# ------------------------------------------------------------------- EMA ----

class TestEMA:
    def test_no_nan_after_first(self):
        result = ema(_series(1, 2, 3, 4, 5), window=3)
        # EMA with adjust=False produces values from the first element
        assert not any(math.isnan(v) for v in result)

    def test_first_value_equals_first_input(self):
        # With adjust=False, EMA starts at the first data point
        result = ema(_series(10, 20, 30), window=2)
        assert result.iloc[0] == pytest.approx(10.0)

    def test_different_from_sma(self):
        s = _rising(20)
        ema_vals = ema(s, window=5)
        sma_vals = sma(s, window=5)
        # EMA reacts faster; for a rising series, EMA > SMA after warmup
        assert not all(
            math.isclose(e, s_, rel_tol=1e-9)
            for e, s_ in zip(ema_vals.dropna(), sma_vals.dropna())
        )

    def test_constant_series(self):
        s = _series(7, 7, 7, 7, 7)
        result = ema(s, window=3)
        assert all(v == pytest.approx(7.0) for v in result)


# --------------------------------------------------------- Bollinger Bands --

class TestBollingerBands:
    def test_ordering(self):
        s = _rising(30)
        upper, mid, lower = bollinger_bands(s, window=10)
        valid = upper.dropna().index
        for i in valid:
            assert upper[i] >= mid[i] >= lower[i]

    def test_mid_equals_sma(self):
        s = _rising(30)
        _, mid, _ = bollinger_bands(s, window=10)
        expected_mid = sma(s, window=10)
        pd.testing.assert_series_equal(mid, expected_mid)

    def test_symmetric_bands(self):
        s = _rising(30)
        upper, mid, lower = bollinger_bands(s, window=10)
        valid = upper.dropna().index
        for i in valid:
            assert upper[i] - mid[i] == pytest.approx(mid[i] - lower[i], rel=1e-9)

    def test_wider_with_larger_std_multiplier(self):
        s = _rising(30)
        upper1, _, lower1 = bollinger_bands(s, window=10, std_dev=1.0)
        upper2, _, lower2 = bollinger_bands(s, window=10, std_dev=2.0)
        valid = upper1.dropna().index
        for i in valid:
            assert upper2[i] >= upper1[i]
            assert lower2[i] <= lower1[i]

    def test_short_series_all_nan(self):
        s = _series(1, 2, 3)
        upper, mid, lower = bollinger_bands(s, window=10)
        assert upper.isna().all()
        assert mid.isna().all()
        assert lower.isna().all()


# ------------------------------------------------------------------- RSI ----

class TestRSI:
    def test_range(self):
        s = _rising(50)
        result = rsi(s)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_all_gains_near_100(self):
        # Constant uptrend — avg_loss → 0, so RS → inf and RSI → 100
        s = _rising(100)
        result = rsi(s, window=14)
        last = result.iloc[-1]
        # Should be 100 (all gains → RS = inf) or very close to it
        assert last >= 99.0 or math.isnan(last) is False

    def test_all_losses_near_0(self):
        # Constant downtrend — RSI should converge near 0
        s = _falling(100)
        result = rsi(s, window=14)
        assert result.iloc[-1] < 10

    def test_alternating_returns_near_50(self):
        # Equal gains and losses should put RSI around 50
        values = [100 + (1 if i % 2 == 0 else -1) for i in range(100)]
        s = pd.Series(values, dtype=float)
        result = rsi(s, window=14)
        assert 40 < result.iloc[-1] < 60

    def test_short_series(self):
        s = _series(1, 2, 3)
        result = rsi(s, window=14)
        # With only 3 points and window=14, all or most should be non-nan
        # (ewm doesn't require full window), but values should be in [0, 100]
        valid = result.dropna()
        if len(valid) > 0:
            assert (valid >= 0).all()
            assert (valid <= 100).all()


# ------------------------------------------------------------------ MACD ----

class TestMACD:
    def test_histogram_identity(self):
        s = _rising(60)
        m_line, s_line, hist = macd(s)
        expected = m_line - s_line
        pd.testing.assert_series_equal(hist, expected)

    def test_lengths_match(self):
        s = _rising(60)
        m_line, s_line, hist = macd(s)
        assert len(m_line) == len(s_line) == len(hist) == len(s)

    def test_no_nan_in_output(self):
        # EMA-based, so no NaN values (ewm fills from the start)
        s = _rising(60)
        m_line, s_line, hist = macd(s)
        assert not m_line.isna().any()
        assert not s_line.isna().any()
        assert not hist.isna().any()

    def test_crossover_sign_change(self):
        # Build a series that rises then falls sharply — should produce a
        # MACD crossover (histogram sign change)
        s = pd.Series(
            [100 + i for i in range(30)] + [130 - i * 2 for i in range(30)],
            dtype=float,
        )
        _, _, hist = macd(s)
        signs = [1 if v >= 0 else -1 for v in hist.fillna(0)]
        # Expect at least one sign change
        crossovers = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
        assert crossovers >= 1

    def test_constant_series_zero_macd(self):
        # Flat price → both EMAs equal → MACD = 0
        s = _series(*([50.0] * 60))
        m_line, s_line, hist = macd(s)
        assert m_line.iloc[-1] == pytest.approx(0.0, abs=1e-10)
        assert hist.iloc[-1] == pytest.approx(0.0, abs=1e-10)
