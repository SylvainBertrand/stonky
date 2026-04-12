"""
Unit tests for app.services.intraday_fetcher.

Mocks `yfinance.Ticker` so the suite stays offline. Verifies the timeframe
mapping, the period→interval translation, the trailing-bar slice, the UTC
tz coercion, and the IntradayUnavailableError window cap.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services import intraday_fetcher
from app.services.intraday_fetcher import (
    INTRADAY_INTERVALS,
    INTRADAY_MAX_DAYS,
    IntradayUnavailableError,
    _fetch_sync,
    fetch_intraday_ohlcv,
    is_intraday_timeframe,
    max_bars_for_timeframe,
)

pytestmark = pytest.mark.unit


def _make_history(bars: int, tz: str | None = "UTC") -> pd.DataFrame:
    """Build a fake yfinance history DataFrame indexed by tz-aware DatetimeIndex."""
    idx = pd.date_range("2026-04-07 13:30", periods=bars, freq="5min", tz=tz)
    return pd.DataFrame(
        {
            "Open": [100.0 + i * 0.1 for i in range(bars)],
            "High": [101.0 + i * 0.1 for i in range(bars)],
            "Low": [99.0 + i * 0.1 for i in range(bars)],
            "Close": [100.5 + i * 0.1 for i in range(bars)],
            "Volume": [1000 + i for i in range(bars)],
        },
        index=idx,
    )


# ── helpers ─────────────────────────────────────────────────────────────────


def test_is_intraday_timeframe_known() -> None:
    for tf in ("1min", "5min", "15min", "30min"):
        assert is_intraday_timeframe(tf)


def test_is_intraday_timeframe_unknown() -> None:
    for tf in ("1h", "4h", "1d", "1w", "1mo", "", "5s", "5m"):
        assert not is_intraday_timeframe(tf)


def test_max_bars_for_timeframe_caps() -> None:
    # 1min: 7 days × 390 bars = 2730
    assert max_bars_for_timeframe("1min") == 2730
    # 5min: 60 days × 78 bars = 4680
    assert max_bars_for_timeframe("5min") == 4680
    assert max_bars_for_timeframe("15min") == 60 * 26
    assert max_bars_for_timeframe("30min") == 60 * 13


def test_max_bars_for_timeframe_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        max_bars_for_timeframe("1h")


# ── _fetch_sync (yfinance call shape) ───────────────────────────────────────


def test_fetch_sync_calls_yfinance_with_correct_interval_and_period() -> None:
    history = _make_history(bars=100, tz="UTC")
    with patch.object(intraday_fetcher.yf, "Ticker") as ticker_cls:
        instance = MagicMock()
        instance.history.return_value = history
        ticker_cls.return_value = instance

        df = _fetch_sync("aapl", "5min", 50)

    ticker_cls.assert_called_once_with("AAPL")
    instance.history.assert_called_once_with(period="60d", interval="5m", auto_adjust=False)
    # Should have tail(50) applied
    assert len(df) == 50
    assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]


def test_fetch_sync_returns_empty_df_on_no_data() -> None:
    with patch.object(intraday_fetcher.yf, "Ticker") as ticker_cls:
        instance = MagicMock()
        instance.history.return_value = pd.DataFrame()
        ticker_cls.return_value = instance

        df = _fetch_sync("ZZZZ", "1min", 100)

    assert df.empty
    assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]


def test_fetch_sync_handles_none_history() -> None:
    with patch.object(intraday_fetcher.yf, "Ticker") as ticker_cls:
        instance = MagicMock()
        instance.history.return_value = None
        ticker_cls.return_value = instance

        df = _fetch_sync("ZZZZ", "1min", 100)

    assert df.empty


def test_fetch_sync_localizes_naive_index_to_utc() -> None:
    history = _make_history(bars=10, tz=None)  # naive
    with patch.object(intraday_fetcher.yf, "Ticker") as ticker_cls:
        instance = MagicMock()
        instance.history.return_value = history
        ticker_cls.return_value = instance

        df = _fetch_sync("AAPL", "5min", 10)

    # All time values should be tz-aware UTC
    times = pd.to_datetime(df["time"])
    assert times.dt.tz is not None
    assert str(times.dt.tz) == "UTC"


def test_fetch_sync_uses_each_interval() -> None:
    """Verify the timeframe → interval / period mapping for every supported tf."""
    history = _make_history(bars=10)
    for tf, interval in INTRADAY_INTERVALS.items():
        with patch.object(intraday_fetcher.yf, "Ticker") as ticker_cls:
            instance = MagicMock()
            instance.history.return_value = history
            ticker_cls.return_value = instance

            _fetch_sync("AAPL", tf, 10)

            instance.history.assert_called_once_with(
                period=f"{INTRADAY_MAX_DAYS[tf]}d",
                interval=interval,
                auto_adjust=False,
            )


def test_fetch_sync_propagates_yfinance_exceptions() -> None:
    with patch.object(intraday_fetcher.yf, "Ticker", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            _fetch_sync("AAPL", "5min", 10)


# ── fetch_intraday_ohlcv (async, validation) ────────────────────────────────


async def test_fetch_intraday_rejects_non_intraday_timeframe() -> None:
    with pytest.raises(ValueError, match="Not an intraday timeframe"):
        await fetch_intraday_ohlcv("AAPL", "1d", 100)


async def test_fetch_intraday_rejects_request_above_window_cap() -> None:
    # 1min cap is 2730 bars
    with pytest.raises(IntradayUnavailableError, match="rolling 7-day window"):
        await fetch_intraday_ohlcv("AAPL", "1min", 5000)


async def test_fetch_intraday_at_cap_is_allowed() -> None:
    # Right at the cap should pass validation and reach yfinance.
    history = _make_history(bars=2730)
    with patch.object(intraday_fetcher.yf, "Ticker") as ticker_cls:
        instance = MagicMock()
        instance.history.return_value = history
        ticker_cls.return_value = instance

        df = await fetch_intraday_ohlcv("AAPL", "1min", 2730)

    assert len(df) == 2730


async def test_fetch_intraday_returns_dataframe_with_expected_columns() -> None:
    history = _make_history(bars=78)
    with patch.object(intraday_fetcher.yf, "Ticker") as ticker_cls:
        instance = MagicMock()
        instance.history.return_value = history
        ticker_cls.return_value = instance

        df = await fetch_intraday_ohlcv("AAPL", "5min", 78)

    assert len(df) == 78
    assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]
    assert df["volume"].dtype.kind == "i"  # integer
