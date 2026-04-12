"""FastAPI router for Paper Trader API endpoints.

Endpoints:
  POST /api/paper-trader/run    — manual trigger; executes the same code path
                                    as the scheduler job and returns run summary.
  POST /api/paper-trader/thesis — Phase 2 thesis-mode: open a position from a
                                    caller-supplied signal without Signal Registry
                                    lookup.

References:
  - Ticket: TC-007 Acceptance Criteria #3
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.paper_trader.scheduler import run_paper_trader
from app.paper_trader.schemas import RunResult, ThesisEntryRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/paper-trader", tags=["paper-trader"])


@router.post("/run", response_model=RunResult)
async def manual_run() -> RunResult:
    """Trigger a full paper-trader cycle immediately.

    Executes the same engine code paths as the 15-minute scheduler job:
      1. Market-hours gate
      2. Exit sweep for all open positions
      3. Process approved signals from Signal Registry
      4. Write Execution Log
      5. Send Discord run-summary

    Returns the run summary JSON regardless of outcome (errors are surfaced
    in the ``errors`` field and ``status`` field).
    """
    try:
        return await run_paper_trader()
    except Exception as exc:
        logger.error("manual_run: unexpected error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/thesis", response_model=RunResult)
async def thesis_entry(body: ThesisEntryRequest) -> RunResult:
    """Phase 2 thesis-mode entry — open a position from caller-supplied parameters.

    Accepts explicit ticker, entry_price (overridden by live price at fill),
    stop, target, size, thesis_id, and direction. Skips Signal Registry lookup
    and uses the same engine validation (R:R check, sizing) as the scheduler.

    This endpoint executes the same code paths as the scheduler run but treats
    the request body as a synthetic approved signal.
    """
    from datetime import UTC, datetime

    from app.config import settings
    from app.market.calendar_service import get_market_status
    from app.paper_trader import discord as disc
    from app.paper_trader import notion_client as nc
    from app.paper_trader.engine import (
        Direction,
        compute_position_size,
        validate_rr,
    )
    from app.services.price_service import TickerNotFoundError, get_current_price

    run_id = f"paper-trader-{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    errors: list[str] = []
    opened = 0
    skipped = 0
    last_url = ""

    market_snapshot = get_market_status()
    market_open = market_snapshot.is_open and market_snapshot.session == "regular"

    if not market_open:
        await nc.write_execution_log(
            run_id=run_id,
            status="failed",
            errors=["market_closed: thesis entries require NYSE regular session"],
        )
        raise HTTPException(
            status_code=422,
            detail="Thesis entries require NYSE regular trading session (9:30–16:00 ET).",
        )

    ticker = body.ticker.upper()
    direction = Direction(body.direction)
    stop = body.stop
    target = body.target

    # Live fill price (never the thesis entry price)
    try:
        quote = await get_current_price(ticker)
        entry_price = quote.price
    except TickerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Ticker not found: {ticker}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Price fetch failed: {exc}") from exc

    # R:R gate
    passes_rr, rr_ratio = validate_rr(
        entry=entry_price,
        stop=stop,
        target=target,
        direction=direction,
        min_rr=settings.paper_trader_min_rr,
    )
    if not passes_rr:
        await nc.write_execution_log(
            run_id=run_id,
            status="failed",
            errors=[f"rr_below_minimum: {rr_ratio:.2f} < {settings.paper_trader_min_rr}"],
        )
        raise HTTPException(
            status_code=422,
            detail=f"R:R ratio {rr_ratio:.2f} is below the minimum {settings.paper_trader_min_rr}.",
        )

    # Position sizing
    size = (
        body.size
        if body.size > 0
        else compute_position_size(
            portfolio_value=settings.paper_trader_portfolio_value,
            risk_pct=settings.paper_trader_risk_pct,
            entry=entry_price,
            stop=stop,
            direction=direction,
        )
    )
    if size <= 0:
        await nc.write_execution_log(
            run_id=run_id,
            status="failed",
            errors=["size_zero: computed position size is zero or negative"],
        )
        raise HTTPException(status_code=422, detail="Computed position size is zero or negative.")

    risk_amount = settings.paper_trader_portfolio_value * settings.paper_trader_risk_pct

    try:
        portfolio_entry = await nc.create_portfolio_position(
            ticker=ticker,
            entry_price=entry_price,
            stop=stop,
            target=target,
            size=size,
            direction=direction.value,
            signal_id="",
            thesis_id=body.thesis_id,
            risk_amount=risk_amount,
            rr_ratio=rr_ratio,
        )
        journal_entry = await nc.create_trade_journal_open(
            ticker=ticker,
            signal_id="",
            entry_price=entry_price,
            stop=stop,
            target=target,
            size=size,
            risk_amount=risk_amount,
            rr_ratio=rr_ratio,
            direction=direction.value,
            portfolio_page_url=portfolio_entry["url"],
        )
        last_url = journal_entry["url"]
        opened = 1
        await disc.send_position_open(
            ticker=ticker,
            entry_price=entry_price,
            stop=stop,
            target=target,
            risk_amount=risk_amount,
            rr_ratio=rr_ratio,
            notion_url=portfolio_entry["url"],
            direction=direction.value,
        )
    except Exception as exc:
        errors.append(str(exc))
        skipped = 1

    status = "success" if opened else "failed"
    await nc.write_execution_log(
        run_id=run_id,
        status=status,
        errors=errors or None,
        output_page_url=last_url,
    )
    await disc.send_run_summary(
        run_id=run_id,
        positions_opened=opened,
        positions_closed=0,
        status=status,
        notion_url=last_url,
    )

    return RunResult(
        run_id=run_id,
        status=status,
        market_open=market_open,
        positions_opened=opened,
        positions_closed=0,
        signals_skipped=skipped,
        errors=errors,
    )
