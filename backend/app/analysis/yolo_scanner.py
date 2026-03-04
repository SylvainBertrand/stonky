"""YOLOv8 chart pattern scan job — orchestrates rendering + inference for watchlists.

Runs as a background job (nightly scheduled or manual trigger).
Stores detections in the pattern_detections table.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.chart_renderer import render_chart_image
from app.analysis.pipeline import fetch_ohlcv_for_symbol
from app.analysis.yolo_screener import YoloDetection, run_yolo_inference
from app.db.session import AsyncSessionLocal
from app.models.enums import (
    PatternType,
    ScanRunStatus,
    SignalDirection,
    TimeframeEnum,
)
from app.models.pattern_detections import PatternDetection
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem

log = logging.getLogger(__name__)

# Marker used to identify YOLO scan runs vs regular scanner runs
YOLO_SCAN_MARKER = "yolo_chart_pattern_scan"

_DIRECTION_MAP: dict[str, SignalDirection] = {
    "bullish": SignalDirection.BULLISH,
    "bearish": SignalDirection.BEARISH,
    "neutral": SignalDirection.NEUTRAL,
}


async def _get_watchlist_symbols(
    db: AsyncSession, watchlist_id: int | None = None
) -> list[tuple[int, str]]:
    """Return (symbol_id, ticker) pairs for the given or default watchlist."""
    query = (
        select(Symbol.id, Symbol.ticker)
        .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
        .where(Symbol.is_active.is_(True))
    )
    if watchlist_id is not None:
        query = query.where(WatchlistItem.watchlist_id == watchlist_id)
    else:
        query = query.join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id).where(
            Watchlist.is_default.is_(True)
        )
    result = await db.execute(query.distinct())
    return [(row[0], row[1]) for row in result.all()]


async def run_yolo_scan_symbol(
    symbol_id: int,
    ticker: str,
    scan_run_id: int,
    db: AsyncSession,
    timeframe: TimeframeEnum = TimeframeEnum.D1,
    bars: int = 120,
) -> list[YoloDetection]:
    """Run YOLOv8 chart pattern scan for a single symbol.

    Steps:
    1. Fetch OHLCV from DB
    2. Render candlestick chart image
    3. Run YOLO inference
    4. Upsert detections into pattern_detections
    """
    df = await fetch_ohlcv_for_symbol(symbol_id, ticker, db, timeframe)
    if df is None or len(df) < 20:
        log.info("YOLO scan %s: insufficient OHLCV data, skipping", ticker)
        return []

    # Render chart (CPU-bound, run in executor)
    loop = asyncio.get_event_loop()
    image_bytes = await loop.run_in_executor(
        None, render_chart_image, df, ticker, timeframe.value, bars
    )
    if isinstance(image_bytes, bytes) and len(image_bytes) == 0:
        log.warning("YOLO scan %s: empty chart image", ticker)
        return []
    if not isinstance(image_bytes, bytes):
        # If output_path was used (shouldn't happen here), read the file
        import pathlib

        image_bytes = pathlib.Path(image_bytes).read_bytes()

    # Run YOLO inference (CPU-bound)
    detections = await loop.run_in_executor(
        None, run_yolo_inference, image_bytes, 0.35, bars
    )

    if not detections:
        log.info("YOLO scan %s: no patterns detected", ticker)
        return []

    # Upsert detections into pattern_detections
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    for det in detections:
        direction = _DIRECTION_MAP.get(det.direction, SignalDirection.NEUTRAL)
        geometry = {
            "bbox": list(det.bbox),
            "bar_start": det.bar_start,
            "bar_end": det.bar_end,
            "bars_in_chart": bars,
        }

        # Upsert: delete existing detection for same symbol/timeframe/pattern/day
        await db.execute(
            delete(PatternDetection).where(
                and_(
                    PatternDetection.symbol_id == symbol_id,
                    PatternDetection.timeframe == timeframe,
                    PatternDetection.pattern_name == det.pattern_name,
                    func.date(PatternDetection.detected_at) == now.date(),
                )
            )
        )

        db.add(
            PatternDetection(
                scan_run_id=scan_run_id,
                symbol_id=symbol_id,
                timeframe=timeframe,
                pattern_type=PatternType.CHART_GEOMETRIC,
                pattern_name=det.pattern_name,
                direction=direction,
                confidence=det.confidence,
                geometry=geometry,
                detected_at=now,
                invalidation=None,
                targets=None,
            )
        )

    await db.flush()
    log.info(
        "YOLO scan %s: stored %d detections: %s",
        ticker,
        len(detections),
        [(d.pattern_name, d.confidence) for d in detections],
    )
    return detections


async def run_yolo_scan_all(
    watchlist_id: int | None = None,
    run_id: int | None = None,
) -> None:
    """Run YOLOv8 chart pattern scan for all watchlist symbols.

    Parameters
    ----------
    watchlist_id : int | None
        Watchlist to scan; uses default watchlist if None.
    run_id : int | None
        Existing ScanRun ID to use (from API endpoint).
        If None, creates a new ScanRun (for scheduler invocations).
    """
    async with AsyncSessionLocal() as db:
        if run_id is not None:
            # Reuse existing ScanRun created by the API endpoint
            scan_run = await db.get(ScanRun, run_id)
            if scan_run is None:
                log.error("YOLO scan: ScanRun %d not found", run_id)
                return
            scan_run.status = ScanRunStatus.RUNNING
            scan_run.started_at = datetime.now(timezone.utc)
            await db.commit()
        else:
            # Create scan run (scheduler invocation)
            scan_run = ScanRun(
                profile_id=None,
                watchlist_id=watchlist_id,
                status=ScanRunStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
                symbols_scanned=0,
                symbols_scored=0,
                error_message=YOLO_SCAN_MARKER,
            )
            db.add(scan_run)
            await db.flush()
            run_id = scan_run.id
            await db.commit()

        log.info("YOLO scan run %d: starting", run_id)

    async with AsyncSessionLocal() as db:
        try:
            symbols = await _get_watchlist_symbols(db, watchlist_id)
            if not symbols:
                log.info("YOLO scan run %d: no watchlist symbols, skipping", run_id)
                scan_run = await db.get(ScanRun, run_id)
                if scan_run:
                    scan_run.status = ScanRunStatus.COMPLETED
                    scan_run.completed_at = datetime.now(timezone.utc)
                    scan_run.error_message = YOLO_SCAN_MARKER
                    await db.commit()
                return

            total_detections = 0
            scanned = 0

            # Process sequentially — YOLO inference is CPU-bound
            for symbol_id, ticker in symbols:
                try:
                    detections = await run_yolo_scan_symbol(
                        symbol_id, ticker, run_id, db
                    )
                    total_detections += len(detections)
                    scanned += 1
                    await db.commit()
                except Exception as exc:
                    log.error("YOLO scan %s failed: %s", ticker, exc)
                    await db.rollback()

            # Update scan run status
            scan_run = await db.get(ScanRun, run_id)
            if scan_run:
                scan_run.status = ScanRunStatus.COMPLETED
                scan_run.completed_at = datetime.now(timezone.utc)
                scan_run.symbols_scanned = len(symbols)
                scan_run.symbols_scored = total_detections
                scan_run.error_message = YOLO_SCAN_MARKER
                await db.commit()

            log.info(
                "YOLO scan run %d: completed. symbols=%d, detections=%d",
                run_id,
                scanned,
                total_detections,
            )

        except Exception as exc:
            log.error("YOLO scan run %d failed: %s", run_id, exc)
            try:
                scan_run = await db.get(ScanRun, run_id)
                if scan_run:
                    scan_run.status = ScanRunStatus.FAILED
                    scan_run.completed_at = datetime.now(timezone.utc)
                    scan_run.error_message = f"{YOLO_SCAN_MARKER}: {str(exc)[:1900]}"
                    await db.commit()
            except Exception as commit_exc:
                log.error("YOLO scan run %d: failed to record error: %s", run_id, commit_exc)
