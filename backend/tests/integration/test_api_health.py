"""
Integration test for the GET /api/health endpoint.

Requires a running TimescaleDB container (provided by the db_container fixture).
"""

import pytest
import httpx

pytestmark = pytest.mark.integration


async def test_health_returns_200(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/api/health")
    assert response.status_code == 200


async def test_health_db_connected(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/api/health")
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] == "connected"


async def test_health_response_shape(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/api/health")
    data = response.json()
    assert "status" in data
    assert "db" in data
