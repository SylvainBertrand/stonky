"""Unit tests for _query_database pagination in notion_client.

Validates that _query_database follows next_cursor pages until has_more=False,
returning all results across all pages.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_response(results: list[dict], has_more: bool, next_cursor: str | None = None) -> dict:
    resp = {"results": results, "has_more": has_more}
    if next_cursor:
        resp["next_cursor"] = next_cursor
    return resp


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents_common.notion_client.settings",
        type("S", (), {"notion_api_key": "test-key"})(),
    )


@pytest.mark.asyncio
async def test_single_page_no_pagination() -> None:
    """Single page (has_more=False) returns all results without a second request."""
    page_results = [{"id": f"p{i}"} for i in range(5)]
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=_make_response(page_results, has_more=False))

    with patch("app.agents_common.notion_client.AsyncClient", return_value=mock_client):
        from app.agents_common.notion_client import _query_database

        results = await _query_database("db-id-123")

    assert results == page_results
    assert mock_client.request.call_count == 1
    call_body = mock_client.request.call_args.kwargs["body"]
    assert "start_cursor" not in call_body


@pytest.mark.asyncio
async def test_multi_page_pagination_fetches_all() -> None:
    """Three pages: verifies cursor is forwarded and all results are concatenated."""
    page1 = [{"id": f"p1-{i}"} for i in range(100)]
    page2 = [{"id": f"p2-{i}"} for i in range(100)]
    page3 = [{"id": f"p3-{i}"} for i in range(50)]

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(
        side_effect=[
            _make_response(page1, has_more=True, next_cursor="cursor-A"),
            _make_response(page2, has_more=True, next_cursor="cursor-B"),
            _make_response(page3, has_more=False),
        ]
    )

    with patch("app.agents_common.notion_client.AsyncClient", return_value=mock_client):
        from app.agents_common.notion_client import _query_database

        results = await _query_database("db-id-456")

    assert len(results) == 250
    assert results == page1 + page2 + page3
    assert mock_client.request.call_count == 3

    # First request has no cursor
    first_body = mock_client.request.call_args_list[0].kwargs["body"]
    assert "start_cursor" not in first_body

    # Second request carries cursor from page 1
    second_body = mock_client.request.call_args_list[1].kwargs["body"]
    assert second_body["start_cursor"] == "cursor-A"

    # Third request carries cursor from page 2
    third_body = mock_client.request.call_args_list[2].kwargs["body"]
    assert third_body["start_cursor"] == "cursor-B"


@pytest.mark.asyncio
async def test_empty_database_returns_empty_list() -> None:
    """Empty results with has_more=False returns [] without extra requests."""
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=_make_response([], has_more=False))

    with patch("app.agents_common.notion_client.AsyncClient", return_value=mock_client):
        from app.agents_common.notion_client import _query_database

        results = await _query_database("db-empty")

    assert results == []
    assert mock_client.request.call_count == 1


@pytest.mark.asyncio
async def test_page_size_100_is_set() -> None:
    """Requests always include page_size=100 to maximise Notion page efficiency."""
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=_make_response([], has_more=False))

    with patch("app.agents_common.notion_client.AsyncClient", return_value=mock_client):
        from app.agents_common.notion_client import _query_database

        await _query_database("db-ps")

    call_body = mock_client.request.call_args.kwargs["body"]
    assert call_body.get("page_size") == 100
