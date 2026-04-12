"""Unit tests for the Paper Trader scheduler logic.

Tests scheduler-level guardrails and orchestration:
  - One-position-per-ticker skip
  - Market-closed gate (no opens/closes when session != regular)
  - Signal already executed skip (board_decision != approved — filtered by Notion query)
  - Rejected/expired signal skip (filtered by Notion query before returning)
  - Signals with rr below minimum are skipped (end-to-end through _process_signals)
  - Zero-size signals are skipped
  - Market-hours gate routes correctly for non-regular sessions

All external I/O (Notion, Discord, price service) is mocked with unittest.mock
so these tests run without any network access or credentials.

References:
  - Ticket: TC-007 Acceptance Criteria #7
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    ticker: str = "AAPL",
    signal_id: str = "sig-001",
    stop: float = 90.0,
    target: float = 125.0,
    direction: str = "long",
    score: float = 0.8,
) -> dict:
    return {
        "id": signal_id,
        "url": "https://notion.so/test",
        "ticker": ticker,
        "board_decision": "approved",
        "agent": "signal-analyst",
        "date": "2026-04-12T10:00:00Z",
        "score": score,
        "entry_price": 100.0,
        "stop": stop,
        "target": target,
        "direction": direction,
        "thesis_id": "",
    }


def _make_position(
    ticker: str = "AAPL",
    entry_price: float = 100.0,
    stop: float = 90.0,
    target: float = 125.0,
    direction: str = "long",
    size: float = 30.0,
) -> dict:
    return {
        "id": "pos-001",
        "url": "https://notion.so/pos-001",
        "ticker": ticker,
        "status": "open",
        "entry_price": entry_price,
        "stop": stop,
        "target": target,
        "size": size,
        "direction": direction,
        "entry_date": "2026-04-11T10:00:00Z",
        "signal_id": "sig-001",
        "thesis_id": "",
        "originating_agent": "paper-trader",
    }


def _regular_market_snapshot() -> MagicMock:
    snap = MagicMock()
    snap.is_open = True
    snap.session = "regular"
    return snap


def _closed_market_snapshot(session: str = "closed") -> MagicMock:
    snap = MagicMock()
    snap.is_open = False
    snap.session = session
    return snap


def _price_quote(price: float = 102.0) -> MagicMock:
    q = MagicMock()
    q.price = price
    return q


# ---------------------------------------------------------------------------
# run_paper_trader — market-closed gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_closed_skips_position_actions() -> None:
    """When NYSE is not in regular session, no positions are opened or closed."""
    with (
        patch(
            "app.paper_trader.scheduler.get_market_status",
            return_value=_closed_market_snapshot(),
        ),
        patch("app.paper_trader.scheduler.nc.write_execution_log", new_callable=AsyncMock),
        patch("app.paper_trader.scheduler.disc.send_run_summary", new_callable=AsyncMock),
        patch(
            "app.paper_trader.scheduler.nc.get_open_positions", new_callable=AsyncMock
        ) as mock_get_pos,
        patch(
            "app.paper_trader.scheduler.nc.get_approved_signals", new_callable=AsyncMock
        ) as mock_get_sigs,
    ):
        from app.paper_trader.scheduler import run_paper_trader

        result = await run_paper_trader()

    assert result.market_open is False
    assert result.positions_opened == 0
    assert result.positions_closed == 0
    # Should never query Notion for signals/positions on a closed market
    mock_get_pos.assert_not_called()
    mock_get_sigs.assert_not_called()


@pytest.mark.asyncio
async def test_pre_market_skips_position_actions() -> None:
    """Pre-market session also prevents any position actions."""
    with (
        patch(
            "app.paper_trader.scheduler.get_market_status",
            return_value=_closed_market_snapshot(session="pre-market"),
        ),
        patch("app.paper_trader.scheduler.nc.write_execution_log", new_callable=AsyncMock),
        patch("app.paper_trader.scheduler.disc.send_run_summary", new_callable=AsyncMock),
        patch(
            "app.paper_trader.scheduler.nc.get_open_positions", new_callable=AsyncMock
        ) as mock_get_pos,
        patch(
            "app.paper_trader.scheduler.nc.get_approved_signals", new_callable=AsyncMock
        ) as mock_get_sigs,
    ):
        from app.paper_trader.scheduler import run_paper_trader

        result = await run_paper_trader()

    assert result.market_open is False
    mock_get_pos.assert_not_called()
    mock_get_sigs.assert_not_called()


# ---------------------------------------------------------------------------
# _process_signals — one-position-per-ticker skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_position_per_ticker_skip() -> None:
    """Signal for ticker already in portfolio must be skipped."""
    existing_position = _make_position(ticker="AAPL")
    signal = _make_signal(ticker="AAPL")

    with (
        patch(
            "app.paper_trader.scheduler.nc.get_approved_signals",
            new_callable=AsyncMock,
            return_value=[signal],
        ),
        patch(
            "app.paper_trader.scheduler.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=[existing_position],
        ),
        patch(
            "app.paper_trader.scheduler.nc.create_portfolio_position",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from app.paper_trader.scheduler import _process_signals

        opened, _, errors, skipped = await _process_signals("run-test")

    assert opened == 0
    assert skipped == 1
    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# _process_signals — rr below minimum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signal_below_minimum_rr_skipped() -> None:
    """Signal with R:R < 1.5 must be skipped (not opened)."""
    # entry_price (live) = 100, stop=90, target=112 → rr=1.2 < 1.5
    signal = _make_signal(ticker="TSLA", stop=90.0, target=112.0)
    price = _price_quote(price=100.0)

    with (
        patch(
            "app.paper_trader.scheduler.nc.get_approved_signals",
            new_callable=AsyncMock,
            return_value=[signal],
        ),
        patch(
            "app.paper_trader.scheduler.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.paper_trader.scheduler.get_current_price",
            new_callable=AsyncMock,
            return_value=price,
        ),
        patch(
            "app.paper_trader.scheduler.nc.create_portfolio_position",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from app.paper_trader.scheduler import _process_signals

        opened, _, errors, skipped = await _process_signals("run-test")

    assert opened == 0
    assert skipped == 1
    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# _process_signals — zero computed size
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_computed_size_skipped() -> None:
    """Signal where entry == stop (invalid setup, zero size) must be skipped."""
    # stop = entry_price (live) → risk_per_share = 0 → size = 0
    signal = _make_signal(ticker="NVDA", stop=100.0, target=130.0)
    price = _price_quote(price=100.0)  # live price == stop

    with (
        patch(
            "app.paper_trader.scheduler.nc.get_approved_signals",
            new_callable=AsyncMock,
            return_value=[signal],
        ),
        patch(
            "app.paper_trader.scheduler.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.paper_trader.scheduler.get_current_price",
            new_callable=AsyncMock,
            return_value=price,
        ),
        patch(
            "app.paper_trader.scheduler.nc.create_portfolio_position",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from app.paper_trader.scheduler import _process_signals

        opened, _, errors, skipped = await _process_signals("run-test")

    assert opened == 0
    assert skipped == 1
    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# _sweep_exits — stop-hit close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_hit_closes_position() -> None:
    """When current price reaches stop, position is closed as a loss."""
    position = _make_position(
        ticker="AAPL", entry_price=100.0, stop=90.0, target=125.0, size=30.0
    )
    # Current price at stop level
    price = _price_quote(price=90.0)

    mock_close = AsyncMock()
    mock_journal = AsyncMock(return_value={"id": "j1", "url": "https://notion.so/j1"})
    mock_discord = AsyncMock()

    with (
        patch(
            "app.paper_trader.scheduler.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=[position],
        ),
        patch(
            "app.paper_trader.scheduler.get_current_price",
            new_callable=AsyncMock,
            return_value=price,
        ),
        patch("app.paper_trader.scheduler.nc.close_portfolio_position", mock_close),
        patch("app.paper_trader.scheduler.nc.create_trade_journal_close", mock_journal),
        patch("app.paper_trader.scheduler.disc.send_position_close", mock_discord),
    ):
        from app.paper_trader.scheduler import _sweep_exits

        closed, last_url, errors = await _sweep_exits("run-test")

    assert closed == 1
    assert errors == []
    # close_portfolio_position called with stop as exit_price
    call_kwargs = mock_close.call_args.kwargs
    assert call_kwargs["exit_price"] == 90.0
    assert call_kwargs["exit_reason"] == "stop-hit"
    assert call_kwargs["r_multiple"] == pytest.approx(-1.0, abs=1e-4)
    assert call_kwargs["realized_pnl"] == pytest.approx(-300.0, abs=1e-4)  # (90-100)*30


@pytest.mark.asyncio
async def test_target_hit_closes_position() -> None:
    """When current price reaches target, position is closed as a win."""
    position = _make_position(
        ticker="MSFT", entry_price=100.0, stop=90.0, target=125.0, size=30.0
    )
    price = _price_quote(price=125.0)

    mock_close = AsyncMock()
    mock_journal = AsyncMock(return_value={"id": "j2", "url": "https://notion.so/j2"})

    with (
        patch(
            "app.paper_trader.scheduler.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=[position],
        ),
        patch(
            "app.paper_trader.scheduler.get_current_price",
            new_callable=AsyncMock,
            return_value=price,
        ),
        patch("app.paper_trader.scheduler.nc.close_portfolio_position", mock_close),
        patch("app.paper_trader.scheduler.nc.create_trade_journal_close", mock_journal),
        patch("app.paper_trader.scheduler.disc.send_position_close", AsyncMock()),
    ):
        from app.paper_trader.scheduler import _sweep_exits

        closed, _, errors = await _sweep_exits("run-test")

    assert closed == 1
    call_kwargs = mock_close.call_args.kwargs
    assert call_kwargs["exit_price"] == 125.0
    assert call_kwargs["exit_reason"] == "target-hit"
    assert call_kwargs["r_multiple"] == pytest.approx(2.5, abs=1e-4)  # (125-100)/10


@pytest.mark.asyncio
async def test_no_exit_when_price_inside_range() -> None:
    """Position inside stop/target range should NOT be closed."""
    position = _make_position(
        ticker="GOOG", entry_price=100.0, stop=90.0, target=125.0, size=30.0
    )
    price = _price_quote(price=105.0)

    mock_close = AsyncMock()

    with (
        patch(
            "app.paper_trader.scheduler.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=[position],
        ),
        patch(
            "app.paper_trader.scheduler.get_current_price",
            new_callable=AsyncMock,
            return_value=price,
        ),
        patch("app.paper_trader.scheduler.nc.close_portfolio_position", mock_close),
    ):
        from app.paper_trader.scheduler import _sweep_exits

        closed, _, errors = await _sweep_exits("run-test")

    assert closed == 0
    mock_close.assert_not_called()


# ---------------------------------------------------------------------------
# run_paper_trader — execution log + discord always called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_log_written_even_on_empty_run() -> None:
    """Execution Log must be written every run, even if nothing happened."""
    mock_log = AsyncMock()
    mock_summary = AsyncMock()

    with (
        patch(
            "app.paper_trader.scheduler.get_market_status",
            return_value=_closed_market_snapshot(),
        ),
        patch("app.paper_trader.scheduler.nc.write_execution_log", mock_log),
        patch("app.paper_trader.scheduler.disc.send_run_summary", mock_summary),
    ):
        from app.paper_trader.scheduler import run_paper_trader

        result = await run_paper_trader()

    mock_log.assert_called_once()
    mock_summary.assert_called_once()
    assert result.status == "success"


@pytest.mark.asyncio
async def test_run_id_format() -> None:
    """Run ID must match pattern paper-trader-{ISO-timestamp}."""
    import re

    with (
        patch(
            "app.paper_trader.scheduler.get_market_status",
            return_value=_closed_market_snapshot(),
        ),
        patch("app.paper_trader.scheduler.nc.write_execution_log", new_callable=AsyncMock),
        patch("app.paper_trader.scheduler.disc.send_run_summary", new_callable=AsyncMock),
    ):
        from app.paper_trader.scheduler import run_paper_trader

        result = await run_paper_trader()

    pattern = r"^paper-trader-\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    assert re.match(pattern, result.run_id), f"Unexpected run_id format: {result.run_id}"


# ---------------------------------------------------------------------------
# Short position PnL sign correctness (end-to-end through _sweep_exits)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_stop_hit_pnl_is_negative() -> None:
    """Short position that hits its stop must produce negative PnL."""
    position = _make_position(
        ticker="SPY", entry_price=100.0, stop=110.0, target=80.0,
        direction="short", size=30.0,
    )
    # current price at stop (110) → stop-hit
    price = _price_quote(price=110.0)

    mock_close = AsyncMock()
    mock_journal = AsyncMock(return_value={"id": "j3", "url": "https://notion.so/j3"})

    with (
        patch(
            "app.paper_trader.scheduler.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=[position],
        ),
        patch(
            "app.paper_trader.scheduler.get_current_price",
            new_callable=AsyncMock,
            return_value=price,
        ),
        patch("app.paper_trader.scheduler.nc.close_portfolio_position", mock_close),
        patch("app.paper_trader.scheduler.nc.create_trade_journal_close", mock_journal),
        patch("app.paper_trader.scheduler.disc.send_position_close", AsyncMock()),
    ):
        from app.paper_trader.scheduler import _sweep_exits

        closed, _, errors = await _sweep_exits("run-short")

    assert closed == 1
    kwargs = mock_close.call_args.kwargs
    assert kwargs["exit_reason"] == "stop-hit"
    assert kwargs["realized_pnl"] < 0   # loss
    assert kwargs["r_multiple"] == pytest.approx(-1.0, abs=1e-4)


@pytest.mark.asyncio
async def test_short_target_hit_pnl_is_positive() -> None:
    """Short position that hits its target must produce positive PnL."""
    position = _make_position(
        ticker="QQQ", entry_price=100.0, stop=110.0, target=85.0,
        direction="short", size=30.0,
    )
    price = _price_quote(price=85.0)

    mock_close = AsyncMock()
    mock_journal = AsyncMock(return_value={"id": "j4", "url": "https://notion.so/j4"})

    with (
        patch(
            "app.paper_trader.scheduler.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=[position],
        ),
        patch(
            "app.paper_trader.scheduler.get_current_price",
            new_callable=AsyncMock,
            return_value=price,
        ),
        patch("app.paper_trader.scheduler.nc.close_portfolio_position", mock_close),
        patch("app.paper_trader.scheduler.nc.create_trade_journal_close", mock_journal),
        patch("app.paper_trader.scheduler.disc.send_position_close", AsyncMock()),
    ):
        from app.paper_trader.scheduler import _sweep_exits

        closed, _, errors = await _sweep_exits("run-short-win")

    assert closed == 1
    kwargs = mock_close.call_args.kwargs
    assert kwargs["exit_reason"] == "target-hit"
    assert kwargs["realized_pnl"] > 0   # win
    assert kwargs["r_multiple"] == pytest.approx(1.5, abs=1e-4)  # (100-85)/10
