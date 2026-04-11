"""
Real-time current price service.

Wraps `yfinance.Ticker.fast_info` for sub-second last-price lookups, with a
process-local thread-safe TTL cache to absorb bursts of agent polling without
hammering yfinance.

The yfinance call is synchronous and network-bound, so it is offloaded to the
default thread pool via `loop.run_in_executor` — consistent with other yfinance
usage in `app.ingestion.fetcher`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass

import yfinance as yf

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PriceQuote:
    """Immutable real-time price snapshot for a single symbol."""

    symbol: str
    price: float
    change_abs: float
    change_pct: float
    timestamp: float  # Unix epoch seconds (UTC)


class TickerNotFoundError(Exception):
    """Raised when yfinance has no usable quote data for a symbol."""


class _CacheEntry:
    __slots__ = ("quote", "expires_at")

    def __init__(self, quote: PriceQuote, expires_at: float) -> None:
        self.quote = quote
        self.expires_at = expires_at


class PriceCache:
    """Thread-safe TTL cache keyed by uppercase ticker symbol."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: dict[str, _CacheEntry] = {}

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def get(self, symbol: str) -> PriceQuote | None:
        now = time.time()
        with self._lock:
            entry = self._store.get(symbol)
            if entry is None or entry.expires_at <= now:
                return None
            return entry.quote

    def set(self, quote: PriceQuote) -> None:
        with self._lock:
            self._store[quote.symbol] = _CacheEntry(quote, time.time() + self._ttl)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Process-wide cache. Tests can call `_cache.clear()` for isolation.
_cache = PriceCache(ttl_seconds=settings.price_cache_ttl_seconds)


def _fetch_quote_sync(symbol: str) -> PriceQuote:
    """
    Synchronous yfinance lookup. Must be invoked from a thread pool.

    Raises:
        TickerNotFoundError: when yfinance returns no last_price/previous_close
            for the symbol (treated as a 404 by the API layer).
    """
    sym = symbol.upper()
    try:
        ticker = yf.Ticker(sym)
        info = ticker.fast_info
        last = info.last_price
        prev_close = info.previous_close
    except Exception as exc:  # noqa: BLE001 — yfinance raises a variety of types
        logger.warning("yfinance lookup failed for %s: %s", sym, exc)
        raise TickerNotFoundError(f"No price data for {sym}") from exc

    if last is None or prev_close is None:
        raise TickerNotFoundError(f"No price data for {sym}")

    last_f = float(last)
    prev_f = float(prev_close)
    change_abs = last_f - prev_f
    change_pct = (change_abs / prev_f * 100.0) if prev_f else 0.0

    return PriceQuote(
        symbol=sym,
        price=round(last_f, 4),
        change_abs=round(change_abs, 4),
        change_pct=round(change_pct, 4),
        timestamp=time.time(),
    )


async def get_current_price(symbol: str) -> PriceQuote:
    """
    Return the current price quote for `symbol`, served from cache when fresh.

    Raises:
        TickerNotFoundError: passed through from `_fetch_quote_sync`.
    """
    sym = symbol.upper()
    cached = _cache.get(sym)
    if cached is not None:
        return cached

    loop = asyncio.get_running_loop()
    quote = await loop.run_in_executor(None, _fetch_quote_sync, sym)
    _cache.set(quote)
    return quote
