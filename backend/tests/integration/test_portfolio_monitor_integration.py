"""Integration test: end-to-end Portfolio Monitor run.

Verifies the full orchestration flow of run_portfolio_monitor():
  1. All 6 in-scope checks fire across a seeded set of open positions
  2. Notion report page created with correct flag sections
  3. Discord webhook called for run summary (mocked)
  4. Immediate critical Discord called for STOP_BREACH (mocked)
  5. Execution Log written (agent=portfolio-monitor, model=stonky-engine)
  6. Signal Registry write happens IFF Andon cord triggers
  7. Signal Registry write does NOT happen when no Andon conditions met

Positions are seeded to cover at least one position per check type:
  - STOP_PROXIMITY  : PROX1 long, near stop (1% away)
  - TARGET_PROXIMITY: PROX2 long, near target (1% away)
  - STOP_BREACH     : BREACH1 long, current <= stop
  - TARGET_BREACH   : BREACH2 short, current <= target
  - CONCENTRATION   : BIG1 — a single position at >10% of portfolio
  - CORRELATION     : CORR1 + CORR2 — same sector+industry
  - STALE           : STALE1 — entry date 10 trading days ago

Notion API, Discord webhook, and price service are all mocked.
Market is forced to "regular" session.

References:
  - Brief: briefs/portfolio-monitor.yaml v2.0.0
  - Ticket: TC-008 Acceptance Criteria #10
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test data builders
# ---------------------------------------------------------------------------


def _regular_market() -> MagicMock:
    snap = MagicMock()
    snap.is_open = True
    snap.session = "regular"
    return snap


def _price(value: float) -> MagicMock:
    q = MagicMock()
    q.price = value
    return q


def _old_date_str() -> str:
    """Return an ISO date string 14 calendar days ago (well past 5 trading days)."""
    old = datetime.now(UTC) - timedelta(days=14)
    return old.isoformat()


def _seeded_positions() -> list[dict]:
    """Seeded open positions: one per check type."""
    return [
        # STOP_PROXIMITY: PROX1 long, stop=100, current=101 → 1% from stop
        {
            "id": "pos-prox1",
            "url": "https://notion.so/prox1",
            "ticker": "PROX1",
            "status": "open",
            "entry_price": 105.0,
            "stop": 100.0,
            "target": 120.0,
            "size": 5.0,
            "direction": "long",
            "entry_date": "2026-04-10T00:00:00+00:00",
            "signal_id": "",
            "thesis_id": "",
            "originating_agent": "paper-trader",
            "sector": "Technology",
            "industry": "Software",
            "current_price": 101.0,
        },
        # TARGET_PROXIMITY: PROX2 long, target=120, current=119 → ~0.8% from target
        {
            "id": "pos-prox2",
            "url": "https://notion.so/prox2",
            "ticker": "PROX2",
            "status": "open",
            "entry_price": 100.0,
            "stop": 90.0,
            "target": 120.0,
            "size": 5.0,
            "direction": "long",
            "entry_date": "2026-04-10T00:00:00+00:00",
            "signal_id": "",
            "thesis_id": "",
            "originating_agent": "paper-trader",
            "sector": "Finance",
            "industry": "Banking",
            "current_price": 119.0,
        },
        # STOP_BREACH: BREACH1 long, current <= stop
        {
            "id": "pos-breach1",
            "url": "https://notion.so/breach1",
            "ticker": "BREACH1",
            "status": "open",
            "entry_price": 105.0,
            "stop": 100.0,
            "target": 120.0,
            "size": 5.0,
            "direction": "long",
            "entry_date": "2026-04-10T00:00:00+00:00",
            "signal_id": "",
            "thesis_id": "",
            "originating_agent": "paper-trader",
            "sector": "Energy",
            "industry": "Oil",
            "current_price": 98.0,
        },
        # TARGET_BREACH: BREACH2 short, current <= target
        {
            "id": "pos-breach2",
            "url": "https://notion.so/breach2",
            "ticker": "BREACH2",
            "status": "open",
            "entry_price": 100.0,
            "stop": 110.0,
            "target": 80.0,
            "size": 5.0,
            "direction": "short",
            "entry_date": "2026-04-10T00:00:00+00:00",
            "signal_id": "",
            "thesis_id": "",
            "originating_agent": "paper-trader",
            "sector": "Healthcare",
            "industry": "Biotech",
            "current_price": 78.0,
        },
        # CONCENTRATION: BIG1 — large size, price $1000, others much smaller
        {
            "id": "pos-big1",
            "url": "https://notion.so/big1",
            "ticker": "BIG1",
            "status": "open",
            "entry_price": 1000.0,
            "stop": 900.0,
            "target": 1200.0,
            "size": 50.0,
            "direction": "long",
            "entry_date": "2026-04-10T00:00:00+00:00",
            "signal_id": "",
            "thesis_id": "",
            "originating_agent": "paper-trader",
            "sector": "Technology",
            "industry": "Software",
            "current_price": 1000.0,
        },
        # CORRELATION: CORR1 + CORR2 — same sector+industry
        {
            "id": "pos-corr1",
            "url": "https://notion.so/corr1",
            "ticker": "CORR1",
            "status": "open",
            "entry_price": 50.0,
            "stop": 45.0,
            "target": 60.0,
            "size": 5.0,
            "direction": "long",
            "entry_date": "2026-04-10T00:00:00+00:00",
            "signal_id": "",
            "thesis_id": "",
            "originating_agent": "paper-trader",
            "sector": "Semiconductors",
            "industry": "Chips",
            "current_price": 52.0,
        },
        {
            "id": "pos-corr2",
            "url": "https://notion.so/corr2",
            "ticker": "CORR2",
            "status": "open",
            "entry_price": 50.0,
            "stop": 45.0,
            "target": 60.0,
            "size": 5.0,
            "direction": "long",
            "entry_date": "2026-04-10T00:00:00+00:00",
            "signal_id": "",
            "thesis_id": "",
            "originating_agent": "paper-trader",
            "sector": "Semiconductors",
            "industry": "Chips",
            "current_price": 52.0,
        },
        # STALE: STALE1 — entry 14 calendar days ago (well past 5 trading days)
        {
            "id": "pos-stale1",
            "url": "https://notion.so/stale1",
            "ticker": "STALE1",
            "status": "open",
            "entry_price": 50.0,
            "stop": 45.0,
            "target": 60.0,
            "size": 5.0,
            "direction": "long",
            "entry_date": _old_date_str(),
            "signal_id": "",
            "thesis_id": "",
            "originating_agent": "paper-trader",
            "sector": "Retail",
            "industry": "Apparel",
            "current_price": 52.0,
        },
    ]


def _prices_for_positions() -> dict[str, float]:
    """Current prices for all seeded positions."""
    return {
        "PROX1": 101.0,
        "PROX2": 119.0,
        "BREACH1": 98.0,  # <= stop 100 → STOP_BREACH
        "BREACH2": 78.0,  # <= target 80 (short) → TARGET_BREACH
        "BIG1": 1000.0,
        "CORR1": 52.0,
        "CORR2": 52.0,
        "STALE1": 52.0,
    }


# ---------------------------------------------------------------------------
# Price service mock helper
# ---------------------------------------------------------------------------


def _make_price_side_effect(prices: dict[str, float]):
    """Returns an async side_effect function that maps ticker → quote mock."""

    async def _side_effect(ticker: str):
        if ticker in prices:
            return _price(prices[ticker])
        raise Exception(f"price_not_found: {ticker}")

    return _side_effect


# ---------------------------------------------------------------------------
# End-to-end run: all 6 checks fire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_6_checks_fire() -> None:
    """Full run: all 6 checks fire across seeded positions, report page created,
    Discord called, Execution Log written, no Andon (< 5 STOP_BREACH)."""
    positions = _seeded_positions()
    prices = _prices_for_positions()

    mock_halt_signals = AsyncMock(return_value=[])

    with (
        patch(
            "app.portfolio_monitor.runner.is_regular_session",
            return_value=True,
        ),
        patch(
            "app.portfolio_monitor.runner.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=positions,
        ),
        patch(
            "app.portfolio_monitor.runner.get_current_price",
            side_effect=_make_price_side_effect(prices),
        ),
        patch(
            "app.portfolio_monitor.runner.nc.get_active_halt_signals",
            new=mock_halt_signals,
        ),
        patch(
            "app.portfolio_monitor.runner.nc.write_execution_log",
            new_callable=AsyncMock,
        ) as mock_exec_log,
        patch(
            "app.portfolio_monitor.runner.nc.write_signal_anomaly",
            new_callable=AsyncMock,
        ) as mock_write_anomaly,
        patch(
            "app.portfolio_monitor.runner.create_run_report",
            new_callable=AsyncMock,
            return_value="https://notion.so/report-001",
        ) as mock_create_report,
        patch(
            "app.portfolio_monitor.runner.send_run_summary",
            new_callable=AsyncMock,
        ) as mock_discord_summary,
        patch(
            "app.portfolio_monitor.runner.send_critical_alert",
            new_callable=AsyncMock,
        ) as mock_critical_alert,
    ):
        from app.portfolio_monitor.runner import run_portfolio_monitor

        result = await run_portfolio_monitor()

    # Status should be success or partial (breaches and data are fine, no data missing)
    assert result.status in ("success", "partial")
    assert result.market_open is True
    assert result.positions_evaluated == len(positions)

    # All 6 check types should appear in flag_types
    assert "STOP_PROXIMITY" in result.flag_types
    assert "TARGET_PROXIMITY" in result.flag_types
    assert "STOP_BREACH" in result.flag_types
    assert "TARGET_BREACH" in result.flag_types
    assert "CONCENTRATION_RISK" in result.flag_types
    assert "CORRELATION_RISK" in result.flag_types
    assert "STALE" in result.flag_types

    # Notion report created
    mock_create_report.assert_called_once()

    # Discord summary called
    mock_discord_summary.assert_called_once()

    # Execution Log written
    mock_exec_log.assert_called_once()
    log_call_kwargs = mock_exec_log.call_args.kwargs
    assert log_call_kwargs["agent"] == "portfolio-monitor"
    assert log_call_kwargs["model"] == "stonky-engine"
    assert log_call_kwargs["run_id"].startswith("portfolio-monitor-")

    # Critical Discord fired for STOP_BREACH and TARGET_BREACH
    critical_calls = mock_critical_alert.call_args_list
    flag_types_alerted = {c.kwargs.get("flag_type") for c in critical_calls}
    assert "STOP_BREACH" in flag_types_alerted
    assert "TARGET_BREACH" in flag_types_alerted

    # No Andon cord — only 1 STOP_BREACH (< 5), so no Signal Registry write
    mock_write_anomaly.assert_not_called()


@pytest.mark.asyncio
async def test_execution_log_written_even_when_market_closed() -> None:
    """Market closed → run exits early but Execution Log is still written."""
    with (
        patch(
            "app.portfolio_monitor.runner.is_regular_session",
            return_value=False,
        ),
        patch(
            "app.portfolio_monitor.runner.nc.write_execution_log",
            new_callable=AsyncMock,
        ) as mock_exec_log,
    ):
        from app.portfolio_monitor.runner import run_portfolio_monitor

        result = await run_portfolio_monitor()

    assert result.market_open is False
    assert result.positions_evaluated == 0
    mock_exec_log.assert_called_once()


@pytest.mark.asyncio
async def test_andon_triggers_signal_registry_write() -> None:
    """5 STOP_BREACH positions → Andon fires → Signal Registry write called."""
    # Create 6 positions all breaching their stop
    breaching_positions = [
        {
            "id": f"pos-b{i}",
            "url": f"https://notion.so/b{i}",
            "ticker": f"BRKN{i}",
            "status": "open",
            "entry_price": 100.0,
            "stop": 100.0,
            "target": 120.0,
            "size": 10.0,
            "direction": "long",
            "entry_date": "2026-04-10T00:00:00+00:00",
            "signal_id": "",
            "thesis_id": "",
            "originating_agent": "paper-trader",
            "sector": "Tech",
            "industry": f"Ind{i}",
            "current_price": 95.0,
        }
        for i in range(6)
    ]
    prices = {f"BRKN{i}": 95.0 for i in range(6)}  # all breaching stop=100

    anomaly_page = {"id": "anomaly-001", "url": "https://notion.so/anomaly-001"}

    with (
        patch(
            "app.portfolio_monitor.runner.is_regular_session",
            return_value=True,
        ),
        patch(
            "app.portfolio_monitor.runner.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=breaching_positions,
        ),
        patch(
            "app.portfolio_monitor.runner.get_current_price",
            side_effect=_make_price_side_effect(prices),
        ),
        patch(
            "app.portfolio_monitor.runner.nc.get_active_halt_signals",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.portfolio_monitor.runner.nc.write_execution_log",
            new_callable=AsyncMock,
        ),
        patch(
            "app.portfolio_monitor.runner.nc.write_signal_anomaly",
            new_callable=AsyncMock,
            return_value=anomaly_page,
        ) as mock_write_anomaly,
        patch(
            "app.portfolio_monitor.runner.create_run_report",
            new_callable=AsyncMock,
            return_value="https://notion.so/report-001",
        ),
        patch(
            "app.portfolio_monitor.runner.send_run_summary",
            new_callable=AsyncMock,
        ),
        patch(
            "app.portfolio_monitor.runner.send_critical_alert",
            new_callable=AsyncMock,
        ),
    ):
        from app.portfolio_monitor.runner import run_portfolio_monitor

        result = await run_portfolio_monitor()

    # Andon triggered
    assert result.andon_triggered is True
    # Signal Registry write called once for the anomaly
    mock_write_anomaly.assert_called_once()
    anomaly_kwargs = mock_write_anomaly.call_args.kwargs
    assert "description" in anomaly_kwargs


@pytest.mark.asyncio
async def test_data_missing_causes_partial_status() -> None:
    """When STONKY-001 returns null for a position, status becomes partial."""
    from app.services.price_service import TickerNotFoundError

    positions = [
        {
            "id": "pos-dm1",
            "url": "https://notion.so/dm1",
            "ticker": "MISSING",
            "status": "open",
            "entry_price": 100.0,
            "stop": 90.0,
            "target": 120.0,
            "size": 10.0,
            "direction": "long",
            "entry_date": "2026-04-10T00:00:00+00:00",
            "signal_id": "",
            "thesis_id": "",
            "originating_agent": "paper-trader",
            "sector": "Tech",
            "industry": "SW",
            "current_price": 0.0,
        },
    ]

    async def _raise_not_found(ticker: str) -> None:
        raise TickerNotFoundError(ticker)

    with (
        patch(
            "app.portfolio_monitor.runner.is_regular_session",
            return_value=True,
        ),
        patch(
            "app.portfolio_monitor.runner.nc.get_open_positions",
            new_callable=AsyncMock,
            return_value=positions,
        ),
        patch(
            "app.portfolio_monitor.runner.get_current_price",
            side_effect=_raise_not_found,
        ),
        patch(
            "app.portfolio_monitor.runner.nc.get_active_halt_signals",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.portfolio_monitor.runner.nc.write_execution_log",
            new_callable=AsyncMock,
        ),
        patch(
            "app.portfolio_monitor.runner.create_run_report",
            new_callable=AsyncMock,
            return_value="https://notion.so/report-001",
        ),
        patch(
            "app.portfolio_monitor.runner.send_run_summary",
            new_callable=AsyncMock,
        ),
        patch(
            "app.portfolio_monitor.runner.send_critical_alert",
            new_callable=AsyncMock,
        ),
    ):
        from app.portfolio_monitor.runner import run_portfolio_monitor

        result = await run_portfolio_monitor()

    # DATA_MISSING should cause partial status
    assert result.status == "partial"
    # DATA_MISSING flag should appear in flag_types
    assert "DATA_MISSING" in result.flag_types
