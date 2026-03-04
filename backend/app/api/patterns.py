"""Chart Patterns API — YOLOv8 pattern detection endpoints.

Endpoints:
  GET  /api/patterns/{symbol}    → latest YOLO detections for a symbol
  POST /api/patterns/scan        → trigger manual YOLO scan (background)
  GET  /api/patterns/scan/status → status of latest YOLO scan run
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.yolo_scanner import YOLO_SCAN_MARKER, run_yolo_scan_all
from app.db.session import get_session
from app.models.enums import PatternType, ScanRunStatus, TimeframeEnum
from app.models.pattern_detections import PatternDetection
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem
from app.schemas.patterns import (
    PatternDetectionResponse,
    PatternScanRunResponse,
    PatternScanStatusResponse,
    SymbolPatternsResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/patterns", tags=["patterns"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_TF_MAP: dict[str, TimeframeEnum] = {
    "1d": TimeframeEnum.D1,
    "1w": TimeframeEnum.W1,
}


@router.get("/{symbol}", response_model=SymbolPatternsResponse)
async def get_symbol_patterns(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="Timeframe: 1d or 1w")] = "1d",
) -> SymbolPatternsResponse:
    """Return latest YOLOv8 chart pattern detections for a symbol."""
    tf_enum = _TF_MAP.get(timeframe, TimeframeEnum.D1)

    # Resolve symbol_id
    sym_result = await session.execute(
        select(Symbol.id).where(Symbol.ticker == symbol.upper())
    )
    symbol_id = sym_result.scalar_one_or_none()
    if symbol_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol {symbol} not found",
        )

    # Get the most recent detection date for this symbol
    latest_date_result = await session.execute(
        select(PatternDetection.detected_at)
        .where(
            PatternDetection.symbol_id == symbol_id,
            PatternDetection.timeframe == tf_enum,
            PatternDetection.pattern_type == PatternType.CHART_GEOMETRIC,
        )
        .order_by(desc(PatternDetection.detected_at))
        .limit(1)
    )
    latest_date = latest_date_result.scalar_one_or_none()

    if latest_date is None:
        return SymbolPatternsResponse(
            symbol=symbol.upper(),
            scanned_at=None,
            detections=[],
        )

    # Fetch all detections from the most recent scan date
    result = await session.execute(
        select(PatternDetection)
        .where(
            PatternDetection.symbol_id == symbol_id,
            PatternDetection.timeframe == tf_enum,
            PatternDetection.pattern_type == PatternType.CHART_GEOMETRIC,
            PatternDetection.detected_at == latest_date,
        )
        .order_by(desc(PatternDetection.confidence))
    )
    rows = result.scalars().all()

    detections = [
        PatternDetectionResponse(
            pattern=row.pattern_name,
            direction=row.direction.value,
            confidence=float(row.confidence),
            bar_start=row.geometry.get("bar_start", 0) if row.geometry else 0,
            bar_end=row.geometry.get("bar_end", 0) if row.geometry else 0,
        )
        for row in rows
    ]

    return SymbolPatternsResponse(
        symbol=symbol.upper(),
        scanned_at=latest_date,
        detections=detections,
    )


@router.post("/scan", response_model=PatternScanRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_pattern_scan(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    watchlist_id: Annotated[
        int | None,
        Query(description="Watchlist to scan; defaults to active watchlist"),
    ] = None,
) -> PatternScanRunResponse:
    """Trigger a manual YOLOv8 chart pattern scan (background task)."""
    # Count symbols to scan
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

    # Create a scan_run to track this job
    scan_run = ScanRun(
        profile_id=None,
        watchlist_id=watchlist_id,
        status=ScanRunStatus.PENDING,
        symbols_scanned=symbol_count,
        symbols_scored=0,
        error_message=YOLO_SCAN_MARKER,
    )
    session.add(scan_run)
    await session.flush()
    run_id = scan_run.id
    await session.commit()

    log.info(
        "Queued YOLO pattern scan run %d: watchlist_id=%s, symbols=%d",
        run_id,
        watchlist_id,
        symbol_count,
    )

    background_tasks.add_task(run_yolo_scan_all, watchlist_id, run_id)
    return PatternScanRunResponse(
        run_id=run_id,
        status="queued",
        symbols_queued=symbol_count,
    )


@router.get("/scan/status", response_model=PatternScanStatusResponse)
async def get_pattern_scan_status(
    session: SessionDep,
) -> PatternScanStatusResponse:
    """Return the status of the most recent YOLO pattern scan run."""
    result = await session.execute(
        select(ScanRun)
        .where(ScanRun.error_message.like(f"{YOLO_SCAN_MARKER}%"))
        .order_by(desc(ScanRun.created_at))
        .limit(1)
    )
    scan_run = result.scalar_one_or_none()

    if scan_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No YOLO pattern scan runs found",
        )

    return PatternScanStatusResponse(
        run_id=scan_run.id,
        status=scan_run.status.value,
        started_at=scan_run.started_at.isoformat() if scan_run.started_at else None,
        completed_at=scan_run.completed_at.isoformat() if scan_run.completed_at else None,
        symbols_scanned=scan_run.symbols_scanned or 0,
        total_detections=scan_run.symbols_scored or 0,
    )
