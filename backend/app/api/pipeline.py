"""Pipeline API — unified scan trigger + live progress.

Endpoints:
  POST /api/pipeline/run    → run full pipeline for all watchlist symbols
  GET  /api/pipeline/status → status of last pipeline run
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import AsyncSessionLocal, get_session
from app.models.enums import ScanRunStatus
from app.models.scan_runs import ScanRun
from app.scheduler.pipeline import (
    PipelineConfig,
    get_watchlist_symbols,
    run_full_pipeline,
)
from app.scheduler.progress import get_progress

log = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

PIPELINE_SCAN_MARKER = "full_pipeline"


async def _run_pipeline_background(
    watchlist_id: int | None,
    run_id: int,
) -> None:
    """Background task that runs the full pipeline."""
    config = PipelineConfig(
        yolo_concurrency=settings.pipeline_yolo_concurrency,
        chronos_concurrency=settings.pipeline_chronos_concurrency,
        synthesis_concurrency=settings.pipeline_synthesis_concurrency,
    )

    async with AsyncSessionLocal() as db:
        scan_run = await db.get(ScanRun, run_id)
        if scan_run:
            scan_run.status = ScanRunStatus.RUNNING
            scan_run.started_at = datetime.now(UTC)
            await db.commit()

    async with AsyncSessionLocal() as db:
        symbols = await get_watchlist_symbols(db, watchlist_id)

    if not symbols:
        log.info("Pipeline run %d: no symbols, skipping", run_id)
        async with AsyncSessionLocal() as db:
            scan_run = await db.get(ScanRun, run_id)
            if scan_run:
                scan_run.status = ScanRunStatus.COMPLETED
                scan_run.completed_at = datetime.now(UTC)
                scan_run.error_message = PIPELINE_SCAN_MARKER
                await db.commit()
        return

    log.info("Pipeline run %d: starting for %d symbols", run_id, len(symbols))

    try:
        summary = await run_full_pipeline(symbols, config, AsyncSessionLocal, run_id)

        async with AsyncSessionLocal() as db:
            scan_run = await db.get(ScanRun, run_id)
            if scan_run:
                scan_run.status = ScanRunStatus.COMPLETED
                scan_run.completed_at = datetime.now(UTC)
                scan_run.symbols_scanned = int(summary["completed"]) + int(summary["failed"])
                scan_run.symbols_scored = int(summary["completed"])
                scan_run.error_message = PIPELINE_SCAN_MARKER
                await db.commit()

        log.info(
            "Pipeline run %d: completed in %.1fs — %d ok, %d failed",
            run_id,
            summary["duration_s"],
            summary["completed"],
            summary["failed"],
        )

    except Exception as exc:
        log.error("Pipeline run %d failed: %s", run_id, exc, exc_info=True)
        async with AsyncSessionLocal() as db:
            scan_run = await db.get(ScanRun, run_id)
            if scan_run:
                scan_run.status = ScanRunStatus.FAILED
                scan_run.completed_at = datetime.now(UTC)
                scan_run.error_message = f"{PIPELINE_SCAN_MARKER}: {str(exc)[:1900]}"
                await db.commit()


@router.post("/run")
async def trigger_pipeline(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    watchlist_id: Annotated[int | None, Query()] = None,
) -> dict[str, Any]:
    """Trigger the full analysis pipeline (YOLO + Chronos + Synthesis) for all symbols."""
    progress = get_progress()
    if progress.status == "running":
        return {
            "status": "already_running",
            "message": "Pipeline is already running.",
        }

    scan_run = ScanRun(
        profile_id=None,
        watchlist_id=watchlist_id,
        status=ScanRunStatus.PENDING,
        symbols_scanned=0,
        symbols_scored=0,
        error_message=PIPELINE_SCAN_MARKER,
    )
    session.add(scan_run)
    await session.flush()
    run_id = scan_run.id
    await session.commit()

    background_tasks.add_task(_run_pipeline_background, watchlist_id, run_id)

    return {
        "run_id": run_id,
        "status": "queued",
    }


@router.get("/status")
async def pipeline_status() -> dict[str, Any]:
    """Return the current pipeline progress."""
    p = get_progress()
    return {
        "status": p.status,
        "started_at": p.started_at.isoformat() if p.started_at else None,
        "completed_at": p.completed_at.isoformat() if p.completed_at else None,
        "symbols_total": p.total,
        "symbols_completed": p.completed,
        "symbols_failed": p.failed,
        "current_symbols": p.current_symbols,
        "estimated_remaining_s": p.estimated_remaining_s,
    }
