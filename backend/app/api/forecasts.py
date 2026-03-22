"""Chronos-2 Forecast API — probabilistic price forecast endpoints.

Endpoints:
  POST /api/forecasts/scan        -> trigger manual forecast scan (background)
  GET  /api/forecasts/scan/status -> status of latest forecast scan run
  GET  /api/forecasts/{symbol}    -> latest forecast for a symbol
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.forecast_scanner import FORECAST_SCAN_MARKER, run_forecast_scan_all
from app.db.session import get_session
from app.models.enums import ScanRunStatus
from app.models.forecast_cache import ForecastCache
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem
from app.schemas.forecasts import (
    ForecastQuantiles,
    ForecastResponse,
    ForecastScanRunResponse,
    ForecastScanStatusResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/scan", response_model=ForecastScanRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_forecast_scan(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    watchlist_id: Annotated[
        int | None,
        Query(description="Watchlist to scan; defaults to active watchlist"),
    ] = None,
) -> ForecastScanRunResponse:
    """Trigger a manual Chronos-2 forecast scan (background task)."""
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
        error_message=FORECAST_SCAN_MARKER,
    )
    session.add(scan_run)
    await session.flush()
    run_id = scan_run.id
    await session.commit()

    log.info(
        "Queued forecast scan run %d: watchlist_id=%s, symbols=%d",
        run_id,
        watchlist_id,
        symbol_count,
    )

    background_tasks.add_task(run_forecast_scan_all, watchlist_id, run_id)
    return ForecastScanRunResponse(
        run_id=run_id,
        status="queued",
        symbols_queued=symbol_count,
    )


@router.get("/scan/status", response_model=ForecastScanStatusResponse)
async def get_forecast_scan_status(
    session: SessionDep,
) -> ForecastScanStatusResponse:
    """Return the status of the most recent forecast scan run."""
    result = await session.execute(
        select(ScanRun)
        .where(ScanRun.error_message.like(f"{FORECAST_SCAN_MARKER}%"))
        .order_by(desc(ScanRun.created_at))
        .limit(1)
    )
    scan_run = result.scalar_one_or_none()

    if scan_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No forecast scan runs found",
        )

    return ForecastScanStatusResponse(
        run_id=scan_run.id,
        status=scan_run.status.value,
        started_at=scan_run.started_at.isoformat() if scan_run.started_at else None,
        completed_at=scan_run.completed_at.isoformat() if scan_run.completed_at else None,
        symbols_scanned=scan_run.symbols_scanned or 0,
        symbols_forecast=scan_run.symbols_scored or 0,
    )


@router.get("/{symbol}", response_model=ForecastResponse | None)
async def get_forecast(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="Timeframe: 1d")] = "1d",
) -> ForecastResponse | None:
    """Return the latest Chronos-2 forecast for a symbol."""
    sym_result = await session.execute(select(Symbol.id).where(Symbol.ticker == symbol.upper()))
    symbol_id = sym_result.scalar_one_or_none()
    if symbol_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol {symbol} not found",
        )

    result = await session.execute(
        select(ForecastCache)
        .where(
            ForecastCache.symbol_id == symbol_id,
            ForecastCache.timeframe == timeframe,
        )
        .order_by(desc(ForecastCache.generated_at))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    return ForecastResponse(
        symbol=symbol.upper(),
        timeframe=row.timeframe,
        generated_at=row.generated_at.isoformat(),
        last_bar_date=row.last_bar_date.isoformat(),
        last_close=float(row.last_close),
        horizon_bars=row.horizon_bars,
        direction=row.direction,
        direction_confidence=float(row.direction_confidence),
        expected_move_pct=float(row.expected_move_pct),
        forecast=ForecastQuantiles(
            median=row.median,
            quantile_10=row.quantile_10,
            quantile_25=row.quantile_25,
            quantile_75=row.quantile_75,
            quantile_90=row.quantile_90,
        ),
    )
