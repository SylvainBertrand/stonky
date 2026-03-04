"""APScheduler daily OHLCV refresh job.

Runs at 4:30 PM Eastern Time every weekday to pick up the day's closing bars.
Only started when settings.scheduler_enabled is True (default).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

logger = logging.getLogger(__name__)


async def daily_ohlcv_refresh() -> None:
    """Fetch incremental OHLCV for every active symbol across all watchlists."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.ingestion.fetcher import fetch_and_store
    from app.models.symbols import Symbol
    from app.models.watchlists import WatchlistItem

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Symbol.ticker)
            .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
            .where(Symbol.is_active.is_(True))
            .distinct()
        )
        tickers = list(result.scalars().all())

    if not tickers:
        logger.info("daily_ohlcv_refresh: no active watchlist symbols, skipping")
        return

    logger.info("daily_ohlcv_refresh: refreshing %d tickers", len(tickers))
    async with AsyncSessionLocal() as session:
        results = await fetch_and_store(session, tickers, incremental=True)
        await session.commit()

    logger.info(
        "daily_ohlcv_refresh: fetched=%d failed=%d",
        results["fetched"],
        results["failed"],
    )


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
        logger.info(
            "Scheduled daily_ohlcv_refresh: weekdays at 16:30 America/New_York"
        )

        from app.analysis.yolo_scanner import run_yolo_scan_all

        scheduler.add_job(
            run_yolo_scan_all,
            CronTrigger(
                hour=6,
                minute=0,
                timezone="America/New_York",
            ),
            id="yolo_nightly_scan",
            replace_existing=True,
        )
        logger.info(
            "Scheduled yolo_nightly_scan: daily at 06:00 America/New_York"
        )
    else:
        logger.info("Scheduler disabled (settings.scheduler_enabled=False)")

    return scheduler
