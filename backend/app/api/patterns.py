"""Chart Patterns API — YOLOv8 pattern detection endpoints.

Endpoints:
  GET  /api/patterns/elliott-wave/{symbol} → Elliott Wave detection for a symbol
  GET  /api/patterns/{symbol}    → latest YOLO detections for a symbol
  POST /api/patterns/scan        → trigger manual YOLO scan (background)
  GET  /api/patterns/scan/status → status of latest YOLO scan run
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Annotated

import numpy as np
import pandas as pd
import pandas_ta as ta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.indicators.elliott_wave import detect_elliott_waves
from app.analysis.swing_points import detect_swing_points
from app.analysis.yolo_scanner import YOLO_SCAN_MARKER, run_yolo_scan_all
from app.db.session import get_session
from app.models.enums import PatternType, ScanRunStatus, TimeframeEnum
from app.models.ohlcv import OHLCV
from app.models.pattern_detections import PatternDetection
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem
from app.schemas.patterns import (
    EWDetectionResponse,
    EWWavePointResponse,
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


@router.get("/elliott-wave/{symbol}", response_model=EWDetectionResponse)
async def get_elliott_wave(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="1d or 1w")] = "1d",
) -> EWDetectionResponse:
    """Return the latest Elliott Wave detection for a symbol."""
    tf_enum = _TF_MAP.get(timeframe, TimeframeEnum.D1)

    # Look up symbol
    sym_result = await session.execute(
        select(Symbol).where(Symbol.ticker == symbol.upper())
    )
    sym = sym_result.scalar_one_or_none()
    if sym is None:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

    # Fetch OHLCV
    bars_result = await session.execute(
        select(OHLCV)
        .where(OHLCV.symbol_id == sym.id, OHLCV.timeframe == tf_enum)
        .order_by(desc(OHLCV.time))
        .limit(300)
    )
    rows = bars_result.scalars().all()
    if not rows:
        return EWDetectionResponse(symbol=symbol.upper())

    rows = list(reversed(rows))
    df = pd.DataFrame([
        {
            "time": r.time.strftime("%Y-%m-%d"),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "open": float(r.open),
            "volume": float(r.volume),
        }
        for r in rows
    ])

    # Run detection in thread pool (CPU-bound)
    def _run(df: pd.DataFrame):  # type: ignore[return]
        atr_ser = ta.atr(df["high"], df["low"], df["close"], length=14)
        sh_bool, _ = detect_swing_points(df["high"], order=5, atr_filter=0.5, atr_series=atr_ser)
        _, sl_bool = detect_swing_points(df["low"], order=5, atr_filter=0.5, atr_series=atr_ser)
        sh_idx = np.where(sh_bool)[0]
        sl_idx = np.where(sl_bool)[0]
        return detect_elliott_waves(df, sh_idx, sl_idx)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_run, df))

    if result.best_wave is None:
        return EWDetectionResponse(symbol=symbol.upper())

    return EWDetectionResponse(
        symbol=symbol.upper(),
        wave_type=result.best_wave.wave_type,
        direction=result.best_wave.direction,
        current_position=result.current_position,
        confidence=round(result.confidence, 4),
        waves=[
            EWWavePointResponse(
                time=wp.time,
                price=wp.price,
                label=wp.label,
                bar_index=wp.bar_index,
            )
            for wp in result.best_wave.waves
        ],
    )


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
            price_top=row.geometry.get("price_top") if row.geometry else None,
            price_bottom=row.geometry.get("price_bottom") if row.geometry else None,
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
