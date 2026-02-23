"""Tests for stonky.data — backend data fetching logic.

All tests mock yfinance.Ticker so no network calls are made.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stonky.data import Quote, StockData, fetch_quote, fetch_stock_data


# ---------------------------------------------------------------- helpers ---

def _make_history(rows: int = 5) -> pd.DataFrame:
    """Return a minimal OHLCV DataFrame with a timezone-aware DatetimeIndex."""
    index = pd.date_range("2025-01-01", periods=rows, freq="B", tz="America/New_York")
    return pd.DataFrame(
        {
            "Open":   [100.0 + i for i in range(rows)],
            "High":   [105.0 + i for i in range(rows)],
            "Low":    [ 95.0 + i for i in range(rows)],
            "Close":  [102.0 + i for i in range(rows)],
            "Volume": [1_000_000] * rows,
        },
        index=index,
    )


def _make_ticker(
    history: pd.DataFrame,
    long_name: str = "Apple Inc.",
    short_name: str = "Apple",
    exchange: str = "NMS",
    currency: str = "USD",
    info_raises: bool = False,
) -> MagicMock:
    ticker = MagicMock()
    ticker.history.return_value = history
    ticker.fast_info.exchange = exchange
    ticker.fast_info.currency = currency
    if info_raises:
        type(ticker).info = property(lambda _: (_ for _ in ()).throw(RuntimeError("info unavailable")))
    else:
        ticker.info = {"longName": long_name, "shortName": short_name}
    return ticker


# ------------------------------------------------------------------ tests ---

class TestFetchStockDataSuccess:
    def test_returns_stock_data_instance(self):
        hist = _make_history()
        with patch("stonky.data.yf.Ticker", return_value=_make_ticker(hist)):
            result = fetch_stock_data("AAPL", "1y")
        assert isinstance(result, StockData)

    def test_symbol_and_period_are_preserved(self):
        hist = _make_history()
        with patch("stonky.data.yf.Ticker", return_value=_make_ticker(hist)):
            result = fetch_stock_data("AAPL", "6mo")
        assert result.symbol == "AAPL"
        assert result.period == "6mo"

    def test_history_dataframe_is_passed_through_unchanged(self):
        hist = _make_history()
        with patch("stonky.data.yf.Ticker", return_value=_make_ticker(hist)):
            result = fetch_stock_data("AAPL", "1y")
        pd.testing.assert_frame_equal(result.history, hist)

    def test_long_name_uses_longName_from_info(self):
        hist = _make_history()
        ticker = _make_ticker(hist, long_name="Apple Inc.", short_name="Apple")
        with patch("stonky.data.yf.Ticker", return_value=ticker):
            result = fetch_stock_data("AAPL", "1y")
        assert result.long_name == "Apple Inc."

    def test_long_name_falls_back_to_shortName_when_longName_missing(self):
        hist = _make_history()
        ticker = _make_ticker(hist)
        ticker.info = {"longName": None, "shortName": "Apple"}
        with patch("stonky.data.yf.Ticker", return_value=ticker):
            result = fetch_stock_data("AAPL", "1y")
        assert result.long_name == "Apple"

    def test_long_name_falls_back_to_symbol_when_both_missing(self):
        hist = _make_history()
        ticker = _make_ticker(hist)
        ticker.info = {"longName": None, "shortName": None}
        with patch("stonky.data.yf.Ticker", return_value=ticker):
            result = fetch_stock_data("AAPL", "1y")
        assert result.long_name == "AAPL"

    def test_long_name_falls_back_to_symbol_when_info_raises(self):
        hist = _make_history()
        ticker = _make_ticker(hist, info_raises=True)
        with patch("stonky.data.yf.Ticker", return_value=ticker):
            result = fetch_stock_data("AAPL", "1y")
        assert result.long_name == "AAPL"

    def test_exchange_and_currency_come_from_fast_info(self):
        hist = _make_history()
        ticker = _make_ticker(hist, exchange="NMS", currency="USD")
        with patch("stonky.data.yf.Ticker", return_value=ticker):
            result = fetch_stock_data("AAPL", "1y")
        assert result.exchange == "NMS"
        assert result.currency == "USD"

    def test_exchange_defaults_to_dash_when_attribute_missing(self):
        hist = _make_history()
        ticker = _make_ticker(hist)
        del ticker.fast_info.exchange  # remove attribute
        ticker.fast_info = MagicMock(spec=["currency"])
        ticker.fast_info.currency = "USD"
        with patch("stonky.data.yf.Ticker", return_value=ticker):
            result = fetch_stock_data("AAPL", "1y")
        assert result.exchange == "—"

    def test_currency_defaults_to_usd_when_attribute_missing(self):
        hist = _make_history()
        ticker = _make_ticker(hist)
        ticker.fast_info = MagicMock(spec=["exchange"])
        ticker.fast_info.exchange = "NMS"
        with patch("stonky.data.yf.Ticker", return_value=ticker):
            result = fetch_stock_data("AAPL", "1y")
        assert result.currency == "USD"


class TestFetchStockDataErrors:
    def test_raises_value_error_when_history_is_empty(self):
        ticker = _make_ticker(pd.DataFrame())
        with patch("stonky.data.yf.Ticker", return_value=ticker):
            with pytest.raises(ValueError, match='No data found for "INVALID"'):
                fetch_stock_data("INVALID", "1y")

    def test_error_message_includes_symbol(self):
        ticker = _make_ticker(pd.DataFrame())
        with patch("stonky.data.yf.Ticker", return_value=ticker):
            with pytest.raises(ValueError, match="XYZ123"):
                fetch_stock_data("XYZ123", "1mo")

    def test_raises_on_ticker_history_exception(self):
        ticker = MagicMock()
        ticker.history.side_effect = ConnectionError("network error")
        with patch("stonky.data.yf.Ticker", return_value=ticker):
            with pytest.raises(ConnectionError):
                fetch_stock_data("AAPL", "1y")


class TestStockDataDataclass:
    def test_fields_are_accessible(self):
        hist = _make_history()
        data = StockData(
            symbol="TSLA",
            period="3mo",
            history=hist,
            long_name="Tesla, Inc.",
            exchange="NMS",
            currency="USD",
        )
        assert data.symbol == "TSLA"
        assert data.period == "3mo"
        assert data.long_name == "Tesla, Inc."
        assert data.exchange == "NMS"
        assert data.currency == "USD"
        pd.testing.assert_frame_equal(data.history, hist)


# ============================================================ fetch_quote ===

def _make_fast_info(
    last_price: float | None = 150.0,
    previous_close: float = 148.0,
    year_high: float = 200.0,
    year_low: float = 120.0,
    exchange: str = "NMS",
    currency: str = "USD",
) -> MagicMock:
    fi = MagicMock()
    fi.last_price = last_price
    fi.regular_market_previous_close = previous_close
    fi.year_high = year_high
    fi.year_low = year_low
    fi.exchange = exchange
    fi.currency = currency
    return fi


def _make_quote_ticker(
    fast_info: MagicMock | None = None,
    long_name: str = "Apple Inc.",
    short_name: str = "Apple",
    info_raises: bool = False,
) -> MagicMock:
    ticker = MagicMock()
    ticker.fast_info = fast_info or _make_fast_info()
    if info_raises:
        type(ticker).info = property(lambda _: (_ for _ in ()).throw(RuntimeError("info unavailable")))
    else:
        ticker.info = {"longName": long_name, "shortName": short_name}
    return ticker


class TestFetchQuoteSuccess:
    def test_returns_quote_instance(self):
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker()):
            result = fetch_quote("AAPL")
        assert isinstance(result, Quote)

    def test_symbol_is_preserved(self):
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker()):
            result = fetch_quote("AAPL")
        assert result.symbol == "AAPL"

    def test_prices_come_from_fast_info(self):
        fi = _make_fast_info(last_price=264.58, previous_close=260.58,
                             year_high=300.0, year_low=150.0)
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker(fi)):
            result = fetch_quote("AAPL")
        assert result.last_price == 264.58
        assert result.previous_close == 260.58
        assert result.year_high == 300.0
        assert result.year_low == 150.0

    def test_change_is_last_minus_previous(self):
        fi = _make_fast_info(last_price=152.0, previous_close=150.0)
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker(fi)):
            result = fetch_quote("AAPL")
        assert result.change == pytest.approx(2.0)

    def test_change_pct_is_correct(self):
        fi = _make_fast_info(last_price=110.0, previous_close=100.0)
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker(fi)):
            result = fetch_quote("AAPL")
        assert result.change_pct == pytest.approx(10.0)

    def test_negative_change(self):
        fi = _make_fast_info(last_price=90.0, previous_close=100.0)
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker(fi)):
            result = fetch_quote("AAPL")
        assert result.change == pytest.approx(-10.0)
        assert result.change_pct == pytest.approx(-10.0)

    def test_long_name_from_info(self):
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker(long_name="Apple Inc.")):
            result = fetch_quote("AAPL")
        assert result.long_name == "Apple Inc."

    def test_long_name_falls_back_to_symbol_when_info_raises(self):
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker(info_raises=True)):
            result = fetch_quote("AAPL")
        assert result.long_name == "AAPL"

    def test_previous_close_defaults_to_last_price_when_missing(self):
        fi = _make_fast_info(last_price=100.0)
        fi.regular_market_previous_close = None
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker(fi)):
            result = fetch_quote("AAPL")
        assert result.previous_close == 100.0
        assert result.change == pytest.approx(0.0)

    def test_year_high_low_default_to_zero_when_missing(self):
        fi = _make_fast_info()
        fi.year_high = None
        fi.year_low = None
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker(fi)):
            result = fetch_quote("AAPL")
        assert result.year_high == 0.0
        assert result.year_low == 0.0


class TestFetchQuoteErrors:
    def test_raises_value_error_when_last_price_is_none(self):
        fi = _make_fast_info(last_price=None)
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker(fi)):
            with pytest.raises(ValueError, match='No data found for "INVALID"'):
                fetch_quote("INVALID")

    def test_change_pct_is_zero_when_previous_close_is_zero(self):
        fi = _make_fast_info(last_price=100.0, previous_close=0.0)
        with patch("stonky.data.yf.Ticker", return_value=_make_quote_ticker(fi)):
            result = fetch_quote("AAPL")
        assert result.change_pct == 0.0
