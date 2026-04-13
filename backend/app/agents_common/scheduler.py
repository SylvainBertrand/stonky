"""Shared scheduler utilities for Stonky autonomous agents.

Provides:
  - is_regular_session() — returns True when NYSE is in regular trading session.

Both paper_trader and portfolio_monitor use this gate before processing any
position actions. They skip (or log-only) when the market is not in a regular
session, but still write the Execution Log on every run.

References:
  - Brief: briefs/paper-trader.yaml v1.0.0
  - Brief: briefs/portfolio-monitor.yaml v2.0.0
  - Ticket: TC-008 Acceptance Criteria #1
"""

from __future__ import annotations


def is_regular_session() -> bool:
    """Return True if the NYSE is currently in a regular trading session.

    Calls the shared market-status service (STONKY-004 equivalent) and checks
    that both ``is_open`` and ``session == "regular"`` are satisfied.

    Used by paper_trader and portfolio_monitor as the market-hours gate before
    executing any position actions.
    """
    from app.market.calendar_service import get_market_status

    snapshot = get_market_status()
    return bool(snapshot.is_open and snapshot.session == "regular")
