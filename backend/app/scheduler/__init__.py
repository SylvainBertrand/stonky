"""APScheduler jobs: OHLCV refresh + unified nightly analysis pipeline.

Runs at 4:30 PM Eastern Time every weekday to pick up the day's closing bars.
Runs the unified analysis pipeline at 6:00 AM (replaces four staggered jobs).
Only started when settings.scheduler_enabled is True (default).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

logger = logging.getLogger(__name__)


async def daily_ohlcv_refresh() -> None:
    """Fetch incremental OHLCV for every active symbol that has stored data.

    Covers watchlist symbols (core universe) plus any symbols hydrated via
    prescore (screener tickers auto-registered by TC-SWE-105).  Only symbols
    that already have at least one OHLCV bar are refreshed — this prevents
    unbounded growth from stale/typo symbols.
    """
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.ingestion.fetcher import fetch_and_store
    from app.models.ohlcv import OHLCV
    from app.models.symbols import Symbol
    from app.models.watchlists import WatchlistItem

    async with AsyncSessionLocal() as session:
        # Core: watchlist tickers (always refreshed)
        wl_result = await session.execute(
            select(Symbol.ticker)
            .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
            .where(Symbol.is_active.is_(True))
            .distinct()
        )
        watchlist_tickers = set(wl_result.scalars().all())

        # Extended: non-watchlist symbols that have stored OHLCV data
        # (hydrated via prescore — screener tickers)
        hydrated_result = await session.execute(
            select(Symbol.ticker)
            .where(Symbol.is_active.is_(True))
            .where(Symbol.id.in_(select(OHLCV.symbol_id).distinct()))
            .distinct()
        )
        hydrated_tickers = set(hydrated_result.scalars().all())

        tickers = sorted(watchlist_tickers | hydrated_tickers)

    if not tickers:
        logger.info("daily_ohlcv_refresh: no active symbols with data, skipping")
        return

    logger.info(
        "daily_ohlcv_refresh: refreshing %d tickers (%d watchlist, %d extended)",
        len(tickers),
        len(watchlist_tickers),
        len(hydrated_tickers - watchlist_tickers),
    )
    async with AsyncSessionLocal() as session:
        results = await fetch_and_store(session, tickers, incremental=True)
        await session.commit()

    logger.info(
        "daily_ohlcv_refresh: fetched=%d failed=%d",
        results["fetched"],
        results["failed"],
    )

    # Also fetch 1H intraday for watchlist symbols only (smaller set, more data)
    from app.models.enums import TimeframeEnum

    wl_list = sorted(watchlist_tickers)
    logger.info("daily_ohlcv_refresh: fetching 1H intraday for %d watchlist tickers", len(wl_list))
    async with AsyncSessionLocal() as session:
        results_1h = await fetch_and_store(
            session, wl_list, timeframe=TimeframeEnum.H1, incremental=True
        )
        await session.commit()
    logger.info(
        "daily_ohlcv_refresh: 1H fetched=%d failed=%d",
        results_1h["fetched"],
        results_1h["failed"],
    )


async def run_nightly_pipeline() -> None:
    """Run the unified analysis pipeline: YOLO + Chronos + Synthesis for all symbols."""
    from app.db.session import AsyncSessionLocal
    from app.models.enums import ScanRunStatus
    from app.models.scan_runs import ScanRun
    from app.scheduler.pipeline import (
        PipelineConfig,
        get_watchlist_symbols,
        run_full_pipeline,
    )

    config = PipelineConfig(
        yolo_concurrency=settings.pipeline_yolo_concurrency,
        chronos_concurrency=settings.pipeline_chronos_concurrency,
        synthesis_concurrency=settings.pipeline_synthesis_concurrency,
    )

    async with AsyncSessionLocal() as db:
        symbols = await get_watchlist_symbols(db)

    if not symbols:
        logger.info("nightly_full_pipeline: no watchlist symbols, skipping")
        return

    # Create a ScanRun record for tracking
    async with AsyncSessionLocal() as db:
        scan_run = ScanRun(
            profile_id=None,
            watchlist_id=None,
            status=ScanRunStatus.RUNNING,
            started_at=datetime.now(UTC),
            symbols_scanned=0,
            symbols_scored=0,
            error_message="full_pipeline",
        )
        db.add(scan_run)
        await db.flush()
        run_id = scan_run.id
        await db.commit()

    logger.info("nightly_full_pipeline: starting for %d symbols (run %d)", len(symbols), run_id)

    try:
        summary = await run_full_pipeline(symbols, config, AsyncSessionLocal, run_id)

        async with AsyncSessionLocal() as db:
            run_record: ScanRun | None = await db.get(ScanRun, run_id)
            if run_record:
                run_record.status = ScanRunStatus.COMPLETED
                run_record.completed_at = datetime.now(UTC)
                run_record.symbols_scanned = int(summary["completed"]) + int(summary["failed"])
                run_record.symbols_scored = int(summary["completed"])
                run_record.error_message = "full_pipeline"
                await db.commit()

        logger.info(
            "nightly_full_pipeline: completed in %.1fs — %d ok, %d failed",
            summary["duration_s"],
            summary["completed"],
            summary["failed"],
        )

    except Exception as exc:
        logger.error("nightly_full_pipeline failed: %s", exc, exc_info=True)
        try:
            async with AsyncSessionLocal() as db:
                run_record_err: ScanRun | None = await db.get(ScanRun, run_id)
                if run_record_err:
                    run_record_err.status = ScanRunStatus.FAILED
                    run_record_err.completed_at = datetime.now(UTC)
                    run_record_err.error_message = f"full_pipeline: {str(exc)[:1900]}"
                    await db.commit()
        except Exception as commit_exc:
            logger.error("nightly_full_pipeline: failed to record error: %s", commit_exc)


def create_scheduler() -> AsyncIOScheduler:
    """Build and configure the APScheduler instance.

    The scheduler is NOT started here — call ``scheduler.start()`` in the
    FastAPI lifespan context.
    """
    scheduler = AsyncIOScheduler()

    if settings.scheduler_enabled:
        scheduler.add_job(
            daily_ohlcv_refresh,
            CronTrigger(
                day_of_week="mon-fri",
                hour=16,
                minute=30,
                timezone="America/New_York",
            ),
            id="daily_ohlcv_refresh",
            replace_existing=True,
        )
        logger.info("Scheduled daily_ohlcv_refresh: weekdays at 16:30 America/New_York")

        scheduler.add_job(
            run_nightly_pipeline,
            CronTrigger(
                hour=6,
                minute=0,
                timezone="America/New_York",
            ),
            id="nightly_full_pipeline",
            replace_existing=True,
        )
        logger.info("Scheduled nightly_full_pipeline: daily at 06:00 America/New_York")

        from app.market.ingestion import run_market_data_refresh

        scheduler.add_job(
            run_market_data_refresh,
            CronTrigger(hour=17, minute=0, timezone="America/New_York"),
            id="market_data_nightly",
            replace_existing=True,
        )
        logger.info("Scheduled market_data_nightly: daily at 17:00 America/New_York")

        from app.paper_trader.scheduler import run_paper_trader

        scheduler.add_job(
            run_paper_trader,
            CronTrigger(
                minute="*/15",
                hour="9-16",
                day_of_week="mon-fri",
                timezone="America/New_York",
            ),
            id="paper_trader_15min",
            replace_existing=True,
        )
        logger.info(
            "Scheduled paper_trader_15min: every 15 min Mon-Fri 09:00-16:00 America/New_York"
        )

        from app.portfolio_monitor.runner import run_portfolio_monitor

        scheduler.add_job(
            run_portfolio_monitor,
            CronTrigger(
                minute="*/15",
                hour="9-16",
                day_of_week="mon-fri",
                timezone="America/New_York",
            ),
            id="portfolio_monitor_15min",
            replace_existing=True,
        )
        logger.info(
            "Scheduled portfolio_monitor_15min: every 15 min Mon-Fri 09:00-16:00 America/New_York"
        )
    else:
        logger.info("Scheduler disabled (settings.scheduler_enabled=False)")

    return scheduler
