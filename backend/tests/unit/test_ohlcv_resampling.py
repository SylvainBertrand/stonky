"""Tests for OHLCV resampling functions."""
from __future__ import annotations

import pandas as pd
import pytest

from app.analysis.pipeline import (
    aggregate_daily_to_monthly,
    aggregate_daily_to_weekly,
    aggregate_hourly_to_4h,
)


@pytest.mark.unit
class TestAggregateDailyToMonthly:
    def test_basic_aggregation(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=60)
        df = pd.DataFrame(
            {
                "time": dates,
                "open": range(100, 160),
                "high": range(105, 165),
                "low": range(95, 155),
                "close": range(101, 161),
                "volume": [1000] * 60,
            }
        )
        result = aggregate_daily_to_monthly(df)
        assert len(result) >= 2  # at least 2 months
        assert list(result.columns) == ["time", "open", "high", "low", "close", "volume"]

    def test_empty_df(self) -> None:
        df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        result = aggregate_daily_to_monthly(df)
        assert len(result) == 0

    def test_volume_summed(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=22)
        df = pd.DataFrame(
            {
                "time": dates,
                "open": [100.0] * 22,
                "high": [110.0] * 22,
                "low": [90.0] * 22,
                "close": [105.0] * 22,
                "volume": [1000] * 22,
            }
        )
        result = aggregate_daily_to_monthly(df)
        # Volume should be summed across all trading days in the month
        assert result["volume"].iloc[0] >= 20000

    def test_ohlc_correct(self) -> None:
        """Open = first day's open, high = max, low = min, close = last day's close."""
        dates = pd.bdate_range("2024-03-01", periods=5)
        df = pd.DataFrame(
            {
                "time": dates,
                "open": [10.0, 11.0, 12.0, 13.0, 14.0],
                "high": [15.0, 20.0, 18.0, 16.0, 19.0],
                "low": [8.0, 9.0, 7.0, 10.0, 11.0],
                "close": [11.0, 12.0, 13.0, 14.0, 15.0],
                "volume": [100, 200, 300, 400, 500],
            }
        )
        result = aggregate_daily_to_monthly(df)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["open"] == 10.0
        assert row["high"] == 20.0
        assert row["low"] == 7.0
        assert row["close"] == 15.0
        assert row["volume"] == 1500


@pytest.mark.unit
class TestAggregateHourlyTo4H:
    def test_basic_aggregation(self) -> None:
        dates = pd.date_range("2024-01-02 09:30", periods=40, freq="h")
        df = pd.DataFrame(
            {
                "time": dates,
                "open": range(100, 140),
                "high": range(105, 145),
                "low": range(95, 135),
                "close": range(101, 141),
                "volume": [500] * 40,
            }
        )
        result = aggregate_hourly_to_4h(df)
        assert len(result) >= 8  # 40 hours / 4 ≈ 10 bars
        assert list(result.columns) == ["time", "open", "high", "low", "close", "volume"]

    def test_empty_df(self) -> None:
        df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        result = aggregate_hourly_to_4h(df)
        assert len(result) == 0

    def test_volume_summed(self) -> None:
        dates = pd.date_range("2024-01-02 00:00", periods=4, freq="h")
        df = pd.DataFrame(
            {
                "time": dates,
                "open": [100.0, 101.0, 102.0, 103.0],
                "high": [105.0, 106.0, 107.0, 108.0],
                "low": [95.0, 96.0, 97.0, 98.0],
                "close": [101.0, 102.0, 103.0, 104.0],
                "volume": [100, 200, 300, 400],
            }
        )
        result = aggregate_hourly_to_4h(df)
        assert len(result) == 1
        assert result["volume"].iloc[0] == 1000


@pytest.mark.unit
class TestAggregateDailyToWeekly:
    def test_basic_aggregation(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=20)
        df = pd.DataFrame(
            {
                "time": dates,
                "open": range(100, 120),
                "high": range(105, 125),
                "low": range(95, 115),
                "close": range(101, 121),
                "volume": [1000] * 20,
            }
        )
        result = aggregate_daily_to_weekly(df)
        assert len(result) >= 3  # 20 days ≈ 4 weeks
        assert list(result.columns) == ["time", "open", "high", "low", "close", "volume"]

    def test_empty_df(self) -> None:
        df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        result = aggregate_daily_to_weekly(df)
        assert len(result) == 0
