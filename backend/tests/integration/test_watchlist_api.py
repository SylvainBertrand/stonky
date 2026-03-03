"""Integration tests for the watchlist CRUD API."""
from __future__ import annotations

import io
import pytest
import httpx


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_watchlists_empty(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/api/watchlists")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
async def test_create_watchlist(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post(
        "/api/watchlists",
        json={"name": "My Tech Picks", "description": "Tech stocks", "is_default": False},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My Tech Picks"
    assert data["description"] == "Tech stocks"
    assert data["is_default"] is False
    assert data["item_count"] == 0
    assert data["items"] == []
    assert "id" in data


@pytest.mark.integration
async def test_create_watchlist_appears_in_list(async_client: httpx.AsyncClient) -> None:
    name = "Dividends 2026 TEST"
    await async_client.post("/api/watchlists", json={"name": name})

    response = await async_client.get("/api/watchlists")
    assert response.status_code == 200
    names = [w["name"] for w in response.json()]
    assert name in names


@pytest.mark.integration
async def test_get_watchlist_by_id(async_client: httpx.AsyncClient) -> None:
    create_resp = await async_client.post("/api/watchlists", json={"name": "Detail Test WL"})
    wl_id = create_resp.json()["id"]

    get_resp = await async_client.get(f"/api/watchlists/{wl_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == wl_id


@pytest.mark.integration
async def test_get_watchlist_404(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/api/watchlists/999999")
    assert response.status_code == 404


@pytest.mark.integration
async def test_delete_watchlist(async_client: httpx.AsyncClient) -> None:
    create_resp = await async_client.post("/api/watchlists", json={"name": "Delete Me WL"})
    wl_id = create_resp.json()["id"]

    delete_resp = await async_client.delete(f"/api/watchlists/{wl_id}")
    assert delete_resp.status_code == 204

    get_resp = await async_client.get(f"/api/watchlists/{wl_id}")
    assert get_resp.status_code == 404


@pytest.mark.integration
async def test_delete_watchlist_404(async_client: httpx.AsyncClient) -> None:
    response = await async_client.delete("/api/watchlists/999999")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Symbol management
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_add_symbol_to_watchlist(async_client: httpx.AsyncClient) -> None:
    create_resp = await async_client.post("/api/watchlists", json={"name": "Add Symbol WL"})
    wl_id = create_resp.json()["id"]

    add_resp = await async_client.post(
        f"/api/watchlists/{wl_id}/symbols",
        json={"ticker": "aapl", "notes": "Core holding"},
    )
    assert add_resp.status_code == 201
    data = add_resp.json()
    assert data["ticker"] == "AAPL"  # uppercased
    assert data["notes"] == "Core holding"


@pytest.mark.integration
async def test_add_symbol_appears_in_detail(async_client: httpx.AsyncClient) -> None:
    create_resp = await async_client.post("/api/watchlists", json={"name": "Symbol Detail WL"})
    wl_id = create_resp.json()["id"]
    await async_client.post(f"/api/watchlists/{wl_id}/symbols", json={"ticker": "MSFT"})

    detail = await async_client.get(f"/api/watchlists/{wl_id}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["item_count"] == 1
    tickers = [item["ticker"] for item in data["items"]]
    assert "MSFT" in tickers


@pytest.mark.integration
async def test_add_symbol_duplicate_returns_409(async_client: httpx.AsyncClient) -> None:
    create_resp = await async_client.post("/api/watchlists", json={"name": "Dup Symbol WL"})
    wl_id = create_resp.json()["id"]

    await async_client.post(f"/api/watchlists/{wl_id}/symbols", json={"ticker": "NVDA"})
    dup_resp = await async_client.post(
        f"/api/watchlists/{wl_id}/symbols", json={"ticker": "NVDA"}
    )
    assert dup_resp.status_code == 409


@pytest.mark.integration
async def test_add_symbol_to_nonexistent_watchlist(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post(
        "/api/watchlists/999999/symbols", json={"ticker": "GOOG"}
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_remove_symbol(async_client: httpx.AsyncClient) -> None:
    create_resp = await async_client.post("/api/watchlists", json={"name": "Remove Symbol WL"})
    wl_id = create_resp.json()["id"]
    await async_client.post(f"/api/watchlists/{wl_id}/symbols", json={"ticker": "TSLA"})

    del_resp = await async_client.delete(f"/api/watchlists/{wl_id}/symbols/TSLA")
    assert del_resp.status_code == 204

    detail = await async_client.get(f"/api/watchlists/{wl_id}")
    assert detail.json()["item_count"] == 0


@pytest.mark.integration
async def test_remove_symbol_not_in_watchlist(async_client: httpx.AsyncClient) -> None:
    create_resp = await async_client.post("/api/watchlists", json={"name": "Remove NF WL"})
    wl_id = create_resp.json()["id"]

    response = await async_client.delete(f"/api/watchlists/{wl_id}/symbols/ZZZZZ")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Default watchlist enforcement
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_only_one_default_watchlist(async_client: httpx.AsyncClient) -> None:
    resp1 = await async_client.post(
        "/api/watchlists", json={"name": "Default One", "is_default": True}
    )
    resp2 = await async_client.post(
        "/api/watchlists", json={"name": "Default Two", "is_default": True}
    )
    assert resp1.status_code == 201
    assert resp2.status_code == 201

    # Only the second should be default now
    all_resp = await async_client.get("/api/watchlists")
    defaults = [w for w in all_resp.json() if w["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "Default Two"


# ---------------------------------------------------------------------------
# Refresh endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_refresh_watchlist_queues_job(async_client: httpx.AsyncClient) -> None:
    create_resp = await async_client.post(
        "/api/watchlists", json={"name": "Refresh WL"}
    )
    wl_id = create_resp.json()["id"]

    response = await async_client.post(f"/api/watchlists/{wl_id}/refresh")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["watchlist_id"] == wl_id


@pytest.mark.integration
async def test_refresh_nonexistent_watchlist(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post("/api/watchlists/999999/refresh")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_status_empty_when_no_logs(async_client: httpx.AsyncClient) -> None:
    create_resp = await async_client.post(
        "/api/watchlists", json={"name": "Status WL"}
    )
    wl_id = create_resp.json()["id"]

    response = await async_client.get(f"/api/watchlists/{wl_id}/status")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# SA Ratings import
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_import_sa_ratings_csv(async_client: httpx.AsyncClient) -> None:
    csv_content = (
        "Ticker,Quant Rating,Momentum,Valuation,Growth\n"
        "AAPL,4.5,A,B+,A-\n"
        "MSFT,4.2,B+,A,B\n"
    )
    response = await async_client.post(
        "/api/watchlists/sa-ratings/import",
        files={"file": ("ratings.csv", csv_content.encode(), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 2
    assert data["errors"] == 0


@pytest.mark.integration
async def test_import_sa_ratings_invalid_file_type(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post(
        "/api/watchlists/sa-ratings/import",
        files={"file": ("ratings.txt", b"some content", "text/plain")},
    )
    assert response.status_code == 400


@pytest.mark.integration
async def test_import_sa_ratings_idempotent(async_client: httpx.AsyncClient) -> None:
    """Importing the same file twice should update, not duplicate."""
    csv_content = "Ticker,Quant Rating\nGOOGL,4.0\n"

    r1 = await async_client.post(
        "/api/watchlists/sa-ratings/import",
        files={"file": ("r1.csv", csv_content.encode(), "text/csv")},
    )
    r2 = await async_client.post(
        "/api/watchlists/sa-ratings/import",
        files={"file": ("r2.csv", csv_content.encode(), "text/csv")},
    )
    assert r1.json()["imported"] == 1
    assert r2.json()["imported"] == 1  # upsert, not double insert


# ---------------------------------------------------------------------------
# Active watchlist endpoints
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_active_watchlist_none(async_client: httpx.AsyncClient) -> None:
    """GET /active returns 404 when no watchlist has is_default=True."""
    response = await async_client.get("/api/watchlists/active")
    assert response.status_code == 404


@pytest.mark.integration
async def test_set_active_watchlist(async_client: httpx.AsyncClient) -> None:
    """PUT /active sets is_default=True; GET /active returns same."""
    resp1 = await async_client.post("/api/watchlists", json={"name": "Active WL A"})
    resp2 = await async_client.post("/api/watchlists", json={"name": "Active WL B"})
    wl1_id = resp1.json()["id"]
    wl2_id = resp2.json()["id"]

    # Set first as active
    set_resp = await async_client.put("/api/watchlists/active", json={"watchlist_id": wl1_id})
    assert set_resp.status_code == 200
    assert set_resp.json()["id"] == wl1_id
    assert set_resp.json()["is_default"] is True

    # GET active returns first
    get_resp = await async_client.get("/api/watchlists/active")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == wl1_id

    # Switch to second
    await async_client.put("/api/watchlists/active", json={"watchlist_id": wl2_id})
    get_resp2 = await async_client.get("/api/watchlists/active")
    assert get_resp2.json()["id"] == wl2_id

    # First should no longer be default
    all_resp = await async_client.get("/api/watchlists")
    defaults = [w for w in all_resp.json() if w["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == wl2_id


@pytest.mark.integration
async def test_rename_watchlist(async_client: httpx.AsyncClient) -> None:
    """PUT /{id} updates the watchlist name."""
    create_resp = await async_client.post("/api/watchlists", json={"name": "Original Name"})
    wl_id = create_resp.json()["id"]

    rename_resp = await async_client.put(
        f"/api/watchlists/{wl_id}", json={"name": "Renamed WL"}
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["name"] == "Renamed WL"

    # Verify via GET
    get_resp = await async_client.get(f"/api/watchlists/{wl_id}")
    assert get_resp.json()["name"] == "Renamed WL"


@pytest.mark.integration
async def test_get_items_with_ratings_empty_ratings(async_client: httpx.AsyncClient) -> None:
    """GET /{id}/items returns items with quant_score=None when no SA ratings exist."""
    create_resp = await async_client.post("/api/watchlists", json={"name": "Items WL"})
    wl_id = create_resp.json()["id"]

    await async_client.post(f"/api/watchlists/{wl_id}/symbols", json={"ticker": "AAPL"})
    await async_client.post(f"/api/watchlists/{wl_id}/symbols", json={"ticker": "MSFT"})

    items_resp = await async_client.get(f"/api/watchlists/{wl_id}/items")
    assert items_resp.status_code == 200
    items = items_resp.json()
    assert len(items) == 2
    tickers = {item["ticker"] for item in items}
    assert tickers == {"AAPL", "MSFT"}
    for item in items:
        assert item["quant_score"] is None
        assert item["momentum_grade"] is None


@pytest.mark.integration
async def test_import_sa_scoped(async_client: httpx.AsyncClient) -> None:
    """POST /{id}/import-sa adds symbols to watchlist and imports ratings."""
    create_resp = await async_client.post("/api/watchlists", json={"name": "SA Import WL"})
    wl_id = create_resp.json()["id"]

    csv_content = (
        "Ticker,Quant Rating,Momentum,Valuation,Growth\n"
        "AAPL,4.5,A,B+,A-\n"
        "MSFT,4.2,B+,A,B\n"
    )
    import_resp = await async_client.post(
        f"/api/watchlists/{wl_id}/import-sa",
        files={"file": ("ratings.csv", csv_content.encode(), "text/csv")},
    )
    assert import_resp.status_code == 200
    data = import_resp.json()
    assert data["added"] == 2
    assert data["skipped"] == 0
    assert data["ratings_imported"] == 2
    assert data["errors"] == 0

    # Symbols should now appear in /items
    items_resp = await async_client.get(f"/api/watchlists/{wl_id}/items")
    assert items_resp.status_code == 200
    tickers = {item["ticker"] for item in items_resp.json()}
    assert "AAPL" in tickers
    assert "MSFT" in tickers

    # Re-import: added=0, skipped=2
    reimport_resp = await async_client.post(
        f"/api/watchlists/{wl_id}/import-sa",
        files={"file": ("ratings2.csv", csv_content.encode(), "text/csv")},
    )
    assert reimport_resp.json()["added"] == 0
    assert reimport_resp.json()["skipped"] == 2


@pytest.mark.integration
async def test_active_watchlist_auto_switch_on_delete(
    async_client: httpx.AsyncClient,
) -> None:
    """Deleting the active watchlist auto-activates another one."""
    resp_a = await async_client.post(
        "/api/watchlists", json={"name": "Auto Switch A", "is_default": True}
    )
    resp_b = await async_client.post("/api/watchlists", json={"name": "Auto Switch B"})
    wl_a_id = resp_a.json()["id"]
    wl_b_id = resp_b.json()["id"]

    # Confirm A is active
    await async_client.put("/api/watchlists/active", json={"watchlist_id": wl_a_id})

    # Delete A
    del_resp = await async_client.delete(f"/api/watchlists/{wl_a_id}")
    assert del_resp.status_code == 204

    # B should now be active
    all_resp = await async_client.get("/api/watchlists")
    wl_list = all_resp.json()
    remaining = [w for w in wl_list if w["id"] == wl_b_id]
    assert len(remaining) == 1
    assert remaining[0]["is_default"] is True
