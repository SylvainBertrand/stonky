"""
Unit tests for app.services.price_service.

Mocks `yfinance.Ticker` so the suite stays offline. Verifies the TTL cache,
quote arithmetic, and not-found handling.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.services import price_service
from app.services.price_service import (
    PriceCache,
    PriceQuote,
    TickerNotFoundError,
    _fetch_quote_sync,
    get_current_price,
)

pytestmark = pytest.mark.unit


def _make_fast_info(last: float | None, prev: float | None) -> MagicMock:
    info = MagicMock()
    info.last_price = last
    info.previous_close = prev
    return info


# ── PriceCache ──────────────────────────────────────────────────────────────


def test_cache_returns_none_when_empty() -> None:
    cache = PriceCache(ttl_seconds=60)
    assert cache.get("AAPL") is None


def test_cache_hit_within_ttl() -> None:
    cache = PriceCache(ttl_seconds=60)
    quote = PriceQuote("AAPL", 175.0, 1.5, 0.86, time.time())
    cache.set(quote)
    assert cache.get("AAPL") == quote


def test_cache_expires_after_ttl() -> None:
    cache = PriceCache(ttl_seconds=0)
    cache.set(PriceQuote("AAPL", 175.0, 1.5, 0.86, time.time()))
    time.sleep(0.01)
    assert cache.get("AAPL") is None


def test_cache_clear_evicts_all_entries() -> None:
    cache = PriceCache(ttl_seconds=60)
    cache.set(PriceQuote("AAPL", 175.0, 1.5, 0.86, time.time()))
    cache.set(PriceQuote("MSFT", 410.0, -2.0, -0.49, time.time()))
    cache.clear()
    assert cache.get("AAPL") is None
    assert cache.get("MSFT") is None


# ── _fetch_quote_sync ───────────────────────────────────────────────────────


def test_fetch_quote_sync_builds_quote_from_fast_info() -> None:
    with patch.object(price_service.yf, "Ticker") as ticker_cls:
        ticker_cls.return_value.fast_info = _make_fast_info(175.0, 173.5)
        quote = _fetch_quote_sync("aapl")

    assert quote.symbol == "AAPL"
    assert quote.price == 175.0
    assert quote.change_abs == pytest.approx(1.5)
    assert quote.change_pct == pytest.approx((1.5 / 173.5) * 100.0, rel=1e-4)
    assert quote.timestamp > 0


def test_fetch_quote_sync_raises_when_last_price_missing() -> None:
    with patch.object(price_service.yf, "Ticker") as ticker_cls:
        ticker_cls.return_value.fast_info = _make_fast_info(None, 100.0)
        with pytest.raises(TickerNotFoundError):
            _fetch_quote_sync("ZZZZZZ")


def test_fetch_quote_sync_raises_when_previous_close_missing() -> None:
    with patch.object(price_service.yf, "Ticker") as ticker_cls:
        ticker_cls.return_value.fast_info = _make_fast_info(100.0, None)
        with pytest.raises(TickerNotFoundError):
            _fetch_quote_sync("ZZZZZZ")


def test_fetch_quote_sync_wraps_yfinance_exceptions() -> None:
    with patch.object(price_service.yf, "Ticker", side_effect=RuntimeError("boom")):
        with pytest.raises(TickerNotFoundError):
            _fetch_quote_sync("AAPL")


def test_fetch_quote_sync_negative_change() -> None:
    with patch.object(price_service.yf, "Ticker") as ticker_cls:
        ticker_cls.return_value.fast_info = _make_fast_info(98.0, 100.0)
        quote = _fetch_quote_sync("AAPL")

    assert quote.change_abs == pytest.approx(-2.0)
    assert quote.change_pct == pytest.approx(-2.0)


# ── get_current_price (async) ───────────────────────────────────────────────


async def test_get_current_price_uses_cache_on_second_call() -> None:
    price_service._cache.clear()

    call_count = 0

    def fake_ticker(_sym: str) -> MagicMock:
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        m.fast_info = _make_fast_info(175.0, 173.5)
        return m

    with patch.object(price_service.yf, "Ticker", side_effect=fake_ticker):
        q1 = await get_current_price("AAPL")
        q2 = await get_current_price("AAPL")

    assert q1 == q2
    assert call_count == 1, "Second call should be served from cache"
    price_service._cache.clear()


async def test_get_current_price_normalizes_symbol_case() -> None:
    price_service._cache.clear()

    with patch.object(price_service.yf, "Ticker") as ticker_cls:
        ticker_cls.return_value.fast_info = _make_fast_info(175.0, 173.5)
        quote = await get_current_price("aapl")

    assert quote.symbol == "AAPL"
    price_service._cache.clear()


async def test_get_current_price_propagates_not_found() -> None:
    price_service._cache.clear()
    with patch.object(price_service.yf, "Ticker") as ticker_cls:
        ticker_cls.return_value.fast_info = _make_fast_info(None, None)
        with pytest.raises(TickerNotFoundError):
            await get_current_price("ZZZZZZ")
