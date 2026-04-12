"""Pydantic schemas for the Paper Trader API endpoints.

References:
  - Ticket: TC-007 Acceptance Criteria #3
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# POST /api/paper-trader/run — response
# ---------------------------------------------------------------------------


class RunResult(BaseModel):
    """Summary returned by a manual or scheduled paper-trader run."""

    run_id: str = Field(description="Unique run identifier (paper-trader-{ISO})")
    status: str = Field(description="success | partial | failed")
    market_open: bool = Field(description="Whether NYSE was open when the run executed")
    positions_opened: int = Field(default=0)
    positions_closed: int = Field(default=0)
    signals_skipped: int = Field(default=0, description="Signals that failed R:R or sizing")
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# POST /api/paper-trader/thesis — request
# ---------------------------------------------------------------------------


class ThesisEntryRequest(BaseModel):
    """Phase 2 thesis-mode manual entry.

    Bypasses Signal Registry lookup; the caller supplies all position
    parameters directly. Execution goes through the same engine code paths as
    the scheduler-driven run.
    """

    ticker: str = Field(description="Equity ticker symbol (e.g. AAPL)")
    entry_price: float = Field(description="Thesis entry price (overridden by live price at fill)")
    stop: float = Field(description="Stop-loss price")
    target: float = Field(description="Profit-target price")
    size: float = Field(
        description="Position size in shares (0 = compute via risk model)",
        default=0.0,
    )
    thesis_id: str = Field(default="", description="Optional thesis reference ID")
    direction: str = Field(default="long", description="long | short")
