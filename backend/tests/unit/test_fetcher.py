"""Unit tests for app.ingestion.fetcher (no DB, no network)."""

from __future__ import annotations

import pandas as pd
import pytest

from app.ingestion.fetcher import _BACKFILL_PERIOD, _YF_INTERVAL, _normalize_df
from app.models.enums import TimeframeEnum

# ---------------------------------------------------------------------------
# _normalize_df
# ---------------------------------------------------------------------------


def _make_raw_daily(n: int = 5) -> pd.DataFrame:
    """Minimal daily yfinance-style DataFrame (tz-naive index)."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {
            "Open": [100.0] * n,
            "High": [105.0] * n,
            "Low": [98.0] * n,
            "Close": [103.0] * n,
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )
    df.index.name = "Date"
    return df


def _make_raw_intraday(n: int = 5) -> pd.DataFrame:
    """Minimal intraday yfinance-style DataFrame (tz-aware UTC index)."""
    idx = pd.date_range("2024-01-01 09:30", periods=n, freq="1h", tz="America/New_York")
    df = pd.DataFrame(
        {
            "Open": [200.0] * n,
            "High": [205.0] * n,
            "Low": [198.0] * n,
            "Close": [202.0] * n,
            "Volume": [500_000] * n,
        },
        index=idx,
    )
    df.index.name = "Datetime"
    return df


@pytest.mark.unit
def test_normalize_df_empty_returns_empty() -> None:
    result = _normalize_df(pd.DataFrame())
    assert result.empty
    assert "time" in result.columns


@pytest.mark.unit
def test_normalize_df_daily_columns() -> None:
    result = _normalize_df(_make_raw_daily())
    assert set(result.columns) == {"time", "open", "high", "low", "close", "volume", "adj_close"}


@pytest.mark.unit
def test_normalize_df_daily_tz_aware_utc() -> None:
    result = _normalize_df(_make_raw_daily())
    assert result["time"].dt.tz is not None
    assert str(result["time"].dt.tz) == "UTC"


@pytest.mark.unit
def test_normalize_df_intraday_tz_converted_to_utc() -> None:
    result = _normalize_df(_make_raw_intraday())
    assert str(result["time"].dt.tz) == "UTC"


@pytest.mark.unit
def test_normalize_df_adj_close_equals_close() -> None:
    result = _normalize_df(_make_raw_daily())
    pd.testing.assert_series_equal(result["adj_close"], result["close"], check_names=False)


@pytest.mark.unit
def test_normalize_df_row_count_preserved() -> None:
    n = 10
    result = _normalize_df(_make_raw_daily(n))
    assert len(result) == n


@pytest.mark.unit
def test_normalize_df_extra_columns_dropped() -> None:
    raw = _make_raw_daily()
    raw["Dividends"] = 0.0
    raw["Stock Splits"] = 0.0
    result = _normalize_df(raw)
    assert "dividends" not in result.columns
    assert "stock_splits" not in result.columns


@pytest.mark.unit
def test_normalize_df_values_correct() -> None:
    raw = _make_raw_daily(1)
    result = _normalize_df(raw)
    assert float(result["open"].iloc[0]) == pytest.approx(100.0)
    assert float(result["high"].iloc[0]) == pytest.approx(105.0)
    assert float(result["low"].iloc[0]) == pytest.approx(98.0)
    assert float(result["close"].iloc[0]) == pytest.approx(103.0)
    assert int(result["volume"].iloc[0]) == 1_000_000


# ---------------------------------------------------------------------------
# Interval / period maps
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_yf_interval_maps_all_timeframes() -> None:
    for tf in TimeframeEnum:
        assert tf in _YF_INTERVAL, f"{tf} missing from _YF_INTERVAL"


@pytest.mark.unit
def test_backfill_period_maps_all_timeframes() -> None:
    for tf in TimeframeEnum:
        assert tf in _BACKFILL_PERIOD, f"{tf} missing from _BACKFILL_PERIOD"


@pytest.mark.unit
def test_d1_interval_is_1d() -> None:
    assert _YF_INTERVAL[TimeframeEnum.D1] == "1d"


@pytest.mark.unit
def test_d1_backfill_period_is_5y() -> None:
    assert _BACKFILL_PERIOD[TimeframeEnum.D1] == "5y"
