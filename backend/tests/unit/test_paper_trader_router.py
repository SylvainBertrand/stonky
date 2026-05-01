"""Unit tests for the Paper Trader router (/thesis endpoint).

Tests the thesis_entry endpoint cash accounting (TC-SWE-196):
  - /thesis must debit cash_balance after opening a position
  - For short positions, reserved_short_collateral must be incremented

All external I/O (Notion, Discord, price service, market status) is mocked.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_market_snapshot(*, is_open: bool = True, session: str = "regular") -> MagicMock:
    snap = MagicMock()
    snap.is_open = is_open
    snap.session = session
    return snap


def _price_quote(price: float = 100.0) -> MagicMock:
    quote = MagicMock()
    quote.price = price
    return quote


def _make_portfolio_state(
    cash_balance: float = 30_000.0,
    equity: float = 30_000.0,
    page_id: str = "state-page-001",
) -> dict:
    return {
        "page_id": page_id,
        "cash_balance": cash_balance,
        "equity": equity,
        "initial_capital": 30_000.0,
        "reserved_short_collateral": 0.0,
    }


@pytest.fixture(autouse=True)
def _mock_calendar_service():
    """Stub out calendar_service before the router imports it."""
    mock_mod = ModuleType("app.market.calendar_service")
    mock_mod.get_market_status = MagicMock(return_value=_make_market_snapshot())
    saved = sys.modules.get("app.market.calendar_service")
    sys.modules["app.market.calendar_service"] = mock_mod
    yield mock_mod
    if saved is None:
        sys.modules.pop("app.market.calendar_service", None)
    else:
        sys.modules["app.market.calendar_service"] = saved


# Patch targets: nc and disc are imported at module level in router
_R = "app.paper_trader.router"


@pytest.mark.asyncio
async def test_thesis_debits_cash_on_long_open(_mock_calendar_service) -> None:
    """TC-SWE-196: /thesis must debit cash_balance by notional after opening a long position."""
    state = _make_portfolio_state(cash_balance=30_000.0)
    mock_update_state = AsyncMock()

    with (
        patch(f"{_R}.get_current_price", new_callable=AsyncMock, return_value=_price_quote(100.0)),
        patch(f"{_R}.validate_rr", return_value=(True, 2.0)),
        patch(f"{_R}.compute_position_size", return_value=50),
        patch(f"{_R}.nc.get_portfolio_state", new_callable=AsyncMock, return_value=state),
        patch(f"{_R}.nc.create_portfolio_position", new_callable=AsyncMock, return_value={"id": "pos-1", "url": "https://notion.so/pos-1"}),
        patch(f"{_R}.nc.create_trade_journal_open", new_callable=AsyncMock, return_value={"id": "j1", "url": "https://notion.so/j1"}),
        patch(f"{_R}.nc.update_portfolio_state", mock_update_state),
        patch(f"{_R}.nc.write_execution_log", new_callable=AsyncMock),
        patch(f"{_R}.disc.send_position_open", new_callable=AsyncMock),
        patch(f"{_R}.disc.send_run_summary", new_callable=AsyncMock),
    ):
        from app.paper_trader.router import thesis_entry
        from app.paper_trader.schemas import ThesisEntryRequest

        result = await thesis_entry(ThesisEntryRequest(
            ticker="AAPL", entry_price=100.0, stop=90.0, target=120.0,
        ))

    assert result.positions_opened == 1
    mock_update_state.assert_called_once()
    update_kwargs = mock_update_state.call_args.kwargs
    # notional = 50 shares * $100 = $5000; cash = 30000 - 5000 = 25000
    assert update_kwargs["cash_balance"] == pytest.approx(25_000.0, abs=1.0)


@pytest.mark.asyncio
async def test_thesis_debits_cash_and_collateral_on_short_open(_mock_calendar_service) -> None:
    """TC-SWE-196: /thesis must debit cash and increment collateral for short positions."""
    state = _make_portfolio_state(cash_balance=30_000.0)
    mock_update_state = AsyncMock()

    with (
        patch(f"{_R}.get_current_price", new_callable=AsyncMock, return_value=_price_quote(100.0)),
        patch(f"{_R}.validate_rr", return_value=(True, 2.0)),
        patch(f"{_R}.compute_position_size", return_value=30),
        patch(f"{_R}.nc.get_portfolio_state", new_callable=AsyncMock, return_value=state),
        patch(f"{_R}.nc.create_portfolio_position", new_callable=AsyncMock, return_value={"id": "pos-2", "url": "https://notion.so/pos-2"}),
        patch(f"{_R}.nc.create_trade_journal_open", new_callable=AsyncMock, return_value={"id": "j2", "url": "https://notion.so/j2"}),
        patch(f"{_R}.nc.update_portfolio_state", mock_update_state),
        patch(f"{_R}.nc.write_execution_log", new_callable=AsyncMock),
        patch(f"{_R}.disc.send_position_open", new_callable=AsyncMock),
        patch(f"{_R}.disc.send_run_summary", new_callable=AsyncMock),
    ):
        from app.paper_trader.router import thesis_entry
        from app.paper_trader.schemas import ThesisEntryRequest

        result = await thesis_entry(ThesisEntryRequest(
            ticker="SPY", entry_price=100.0, stop=110.0, target=85.0, direction="short",
        ))

    assert result.positions_opened == 1
    mock_update_state.assert_called_once()
    update_kwargs = mock_update_state.call_args.kwargs
    # notional = 30 * 100 = 3000; cash = 30000 - 3000 = 27000
    assert update_kwargs["cash_balance"] == pytest.approx(27_000.0, abs=1.0)
    assert update_kwargs["reserved_short_collateral"] == pytest.approx(3_000.0, abs=1.0)
