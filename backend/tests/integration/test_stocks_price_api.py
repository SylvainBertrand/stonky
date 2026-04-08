"""
Integration test for GET /api/stocks/{symbol}/price.

Makes a real yfinance call against AAPL — flaky if the network is unavailable
or yfinance rate-limits. Marked `slow` so the default unit suite skips it.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import price_service

pytestmark = [pytest.mark.integration, pytest.mark.slow]


async def test_price_endpoint_returns_valid_quote_for_aapl(
    async_client: httpx.AsyncClient,
) -> None:
    price_service._cache.clear()
    response = await async_client.get("/api/stocks/AAPL/price")
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["symbol"] == "AAPL"
    assert isinstance(data["price"], (int, float))
    assert data["price"] > 0
    assert isinstance(data["change_abs"], (int, float))
    assert isinstance(data["change_pct"], (int, float))
    assert isinstance(data["timestamp"], (int, float))
    assert data["timestamp"] > 0
    price_service._cache.clear()


async def test_price_endpoint_returns_404_for_invalid_ticker(
    async_client: httpx.AsyncClient,
) -> None:
    price_service._cache.clear()
    response = await async_client.get("/api/stocks/ZZZZZZZZZZ/price")
    assert response.status_code == 404
    price_service._cache.clear()
