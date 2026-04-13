"""FastAPI router for Portfolio Monitor API endpoints.

Endpoints:
  POST /api/portfolio-monitor/run  — manual trigger; executes the same code
                                      path as the scheduler job.

References:
  - Brief: briefs/portfolio-monitor.yaml v2.0.0
  - Ticket: TC-008 Acceptance Criteria #4
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.portfolio_monitor.runner import RunSummary, run_portfolio_monitor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio-monitor", tags=["portfolio-monitor"])


@router.post("/run", response_model=RunSummary)
async def manual_run() -> RunSummary:
    """Trigger a full portfolio-monitor cycle immediately.

    Executes the same engine code paths as the 15-minute scheduler job:
      1. Market-hours gate (via /api/market/status)
      2. Read open positions from Paper Portfolio DB
      3. Fetch live prices via STONKY-001
      4. Run all 6 in-scope checks (STOP_PROXIMITY, TARGET_PROXIMITY,
         STOP_BREACH/TARGET_BREACH, CONCENTRATION_RISK, CORRELATION_RISK, STALE)
      5. Evaluate Andon cord triggers
      6. Write Notion report page
      7. Send Discord run summary
      8. Write Execution Log row

    Returns the run summary JSON including all flags raised.
    Check 6 (THESIS_DRIFT) is out of scope — runs weekly via research mode.
    """
    try:
        return await run_portfolio_monitor()
    except Exception as exc:
        logger.error("portfolio_monitor manual_run: unexpected error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
