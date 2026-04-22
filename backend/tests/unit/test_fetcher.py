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


# ---------------------------------------------------------------------------
# _batch_download_sync
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_batch_download_sync_empty_tickers() -> None:
    from app.ingestion.fetcher import _batch_download_sync

    result = _batch_download_sync([], "1y", "1d")
    assert result == {}


@pytest.mark.unit
def test_batch_download_sync_single_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single-ticker download returns a flat DataFrame (not MultiIndex)."""
    from app.ingestion.fetcher import _batch_download_sync

    raw = _make_raw_daily(10)
    monkeypatch.setattr("app.ingestion.fetcher.yf.download", lambda *a, **kw: raw)

    result = _batch_download_sync(["AAPL"], "1y", "1d")
    assert "AAPL" in result
    assert len(result["AAPL"]) == 10


@pytest.mark.unit
def test_batch_download_sync_multi_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multi-ticker download returns a MultiIndex DataFrame."""
    from app.ingestion.fetcher import _batch_download_sync

    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    arrays = {
        ("AAPL", "Open"): [100.0] * 5,
        ("AAPL", "High"): [105.0] * 5,
        ("AAPL", "Low"): [98.0] * 5,
        ("AAPL", "Close"): [103.0] * 5,
        ("AAPL", "Volume"): [1_000_000] * 5,
        ("NVDA", "Open"): [200.0] * 5,
        ("NVDA", "High"): [210.0] * 5,
        ("NVDA", "Low"): [195.0] * 5,
        ("NVDA", "Close"): [205.0] * 5,
        ("NVDA", "Volume"): [2_000_000] * 5,
    }
    multi_df = pd.DataFrame(arrays, index=idx)
    multi_df.index.name = "Date"
    multi_df.columns = pd.MultiIndex.from_tuples(multi_df.columns)

    monkeypatch.setattr("app.ingestion.fetcher.yf.download", lambda *a, **kw: multi_df)

    result = _batch_download_sync(["AAPL", "NVDA"], "1y", "1d")
    assert "AAPL" in result
    assert "NVDA" in result
    assert len(result["AAPL"]) == 5
    assert len(result["NVDA"]) == 5


# ---------------------------------------------------------------------------
# ensure_symbols
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensure_symbols_creates_missing(db_session: "AsyncSession") -> None:
    """ensure_symbols creates new Symbol records for unknown tickers."""
    from app.ingestion.fetcher import ensure_symbols

    result = await ensure_symbols(db_session, ["AAPL", "NVDA", "TSLA"])
    await db_session.commit()

    assert len(result) == 3
    assert "AAPL" in result
    assert "NVDA" in result
    assert "TSLA" in result
    assert all(isinstance(v, int) for v in result.values())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensure_symbols_idempotent(db_session: "AsyncSession") -> None:
    """Calling ensure_symbols twice with overlapping tickers is safe."""
    from app.ingestion.fetcher import ensure_symbols

    result1 = await ensure_symbols(db_session, ["AAPL", "NVDA"])
    await db_session.flush()
    result2 = await ensure_symbols(db_session, ["NVDA", "TSLA"])
    await db_session.flush()

    # NVDA should have the same ID in both calls
    assert result1["NVDA"] == result2["NVDA"]
    assert "TSLA" in result2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensure_symbols_normalizes_case(db_session: "AsyncSession") -> None:
    """Ticker case is normalized to uppercase."""
    from app.ingestion.fetcher import ensure_symbols

    result = await ensure_symbols(db_session, ["aapl", "Nvda"])
    assert "AAPL" in result
    assert "NVDA" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensure_symbols_deduplicates_input(db_session: "AsyncSession") -> None:
    """Duplicate tickers in input don't cause errors."""
    from app.ingestion.fetcher import ensure_symbols

    result = await ensure_symbols(db_session, ["AAPL", "aapl", "AAPL"])
    assert len(result) == 1
    assert "AAPL" in result
