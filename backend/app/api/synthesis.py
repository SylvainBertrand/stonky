"""LLM Synthesis API — trade setup analysis endpoints.

Endpoints:
  GET  /api/synthesis/{symbol}    -> latest synthesis result for a symbol
  POST /api/synthesis/scan        -> trigger manual synthesis scan (background)
  GET  /api/synthesis/scan/status -> status of latest synthesis scan run
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.synthesis_scanner import SYNTHESIS_SCAN_MARKER, run_synthesis_scan_all
from app.db.session import get_session
from app.models.enums import ScanRunStatus
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.synthesis_result import SynthesisResult
from app.models.watchlists import Watchlist, WatchlistItem
from app.schemas.synthesis import (
    SynthesisResponse,
    SynthesisScanRunResponse,
    SynthesisScanStatusResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/synthesis", tags=["synthesis"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/scan",
    response_model=SynthesisScanRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_synthesis_scan(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    watchlist_id: Annotated[
        int | None,
        Query(description="Watchlist to scan; defaults to active watchlist"),
    ] = None,
) -> SynthesisScanRunResponse:
    """Trigger a manual LLM synthesis scan (background task)."""
    query = (
        select(Symbol.id)
        .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
        .where(Symbol.is_active.is_(True))
    )
    if watchlist_id is not None:
        query = query.where(WatchlistItem.watchlist_id == watchlist_id)
    else:
        query = query.join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id).where(
            Watchlist.is_default.is_(True)
        )
    sym_result = await session.execute(query.distinct())
    symbol_count = len(sym_result.all())

    if symbol_count == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No symbols in watchlist. Add tickers to a watchlist first.",
        )

    scan_run = ScanRun(
        profile_id=None,
        watchlist_id=watchlist_id,
        status=ScanRunStatus.PENDING,
        symbols_scanned=symbol_count,
        symbols_scored=0,
        error_message=SYNTHESIS_SCAN_MARKER,
    )
    session.add(scan_run)
    await session.flush()
    run_id = scan_run.id
    await session.commit()

    log.info(
        "Queued synthesis scan run %d: watchlist_id=%s, symbols=%d",
        run_id,
        watchlist_id,
        symbol_count,
    )

    background_tasks.add_task(run_synthesis_scan_all, watchlist_id, run_id)
    return SynthesisScanRunResponse(
        run_id=run_id,
        status="queued",
        symbols_queued=symbol_count,
    )


@router.get("/scan/status", response_model=SynthesisScanStatusResponse)
async def get_synthesis_scan_status(
    session: SessionDep,
) -> SynthesisScanStatusResponse:
    """Return the status of the most recent synthesis scan run."""
    result = await session.execute(
        select(ScanRun)
        .where(ScanRun.error_message.like(f"{SYNTHESIS_SCAN_MARKER}%"))
        .order_by(desc(ScanRun.created_at))
        .limit(1)
    )
    scan_run = result.scalar_one_or_none()

    if scan_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No synthesis scan runs found",
        )

    return SynthesisScanStatusResponse(
        run_id=scan_run.id,
        status=scan_run.status.value,
        started_at=scan_run.started_at.isoformat() if scan_run.started_at else None,
        completed_at=scan_run.completed_at.isoformat() if scan_run.completed_at else None,
        symbols_scanned=scan_run.symbols_scanned or 0,
        symbols_synthesized=scan_run.symbols_scored or 0,
    )


@router.get("/{symbol}", response_model=SynthesisResponse | None)
async def get_synthesis(
    symbol: str,
    session: SessionDep,
) -> SynthesisResponse | None:
    """Return the latest LLM synthesis result for a symbol."""
    sym_result = await session.execute(
        select(Symbol.id).where(Symbol.ticker == symbol.upper())
    )
    symbol_id = sym_result.scalar_one_or_none()
    if symbol_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol {symbol} not found",
        )

    result = await session.execute(
        select(SynthesisResult)
        .where(SynthesisResult.symbol_id == symbol_id)
        .order_by(desc(SynthesisResult.generated_at))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    return SynthesisResponse(
        symbol=symbol.upper(),
        generated_at=row.generated_at.isoformat(),
        setup_type=row.setup_type,
        bias=row.bias,
        confidence=row.confidence,
        summary=row.summary,
        signal_confluence=row.signal_confluence,
        signal_conflicts=row.signal_conflicts,
        entry=float(row.entry) if row.entry is not None else None,
        stop=float(row.stop) if row.stop is not None else None,
        target=float(row.target) if row.target is not None else None,
        risk_reward=float(row.risk_reward) if row.risk_reward is not None else None,
        key_risk=row.key_risk,
        parse_error=row.parse_error,
    )
