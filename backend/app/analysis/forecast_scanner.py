"""Chronos-2 forecast batch job — runs forecasts for all watchlist symbols.

Runs as a background job (nightly scheduled or manual trigger).
Stores results in the forecast_cache table.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.forecaster import run_forecast
from app.analysis.pipeline import fetch_ohlcv_for_symbol
from app.db.session import AsyncSessionLocal
from app.models.enums import ScanRunStatus, TimeframeEnum
from app.models.forecast_cache import ForecastCache
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem

log = logging.getLogger(__name__)

FORECAST_SCAN_MARKER = "chronos_forecast"
RETENTION_DAYS = 7


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


async def _purge_old_forecasts(db: AsyncSession, symbol_id: int) -> None:
    """Remove forecasts older than RETENTION_DAYS for a symbol."""
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    await db.execute(
        delete(ForecastCache).where(
            and_(
                ForecastCache.symbol_id == symbol_id,
                ForecastCache.generated_at < cutoff,
            )
        )
    )


async def run_forecast_scan_all(
    watchlist_id: int | None = None,
    run_id: int | None = None,
) -> None:
    """Run Chronos-2 forecast for all watchlist symbols.

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
            scan_run = await db.get(ScanRun, run_id)
            if scan_run is None:
                log.error("Forecast scan: ScanRun %d not found", run_id)
                return
            scan_run.status = ScanRunStatus.RUNNING
            scan_run.started_at = datetime.now(UTC)
            await db.commit()
        else:
            scan_run = ScanRun(
                profile_id=None,
                watchlist_id=watchlist_id,
                status=ScanRunStatus.RUNNING,
                started_at=datetime.now(UTC),
                symbols_scanned=0,
                symbols_scored=0,
                error_message=FORECAST_SCAN_MARKER,
            )
            db.add(scan_run)
            await db.flush()
            run_id = scan_run.id
            await db.commit()

        log.info("Forecast scan run %d: starting", run_id)

    async with AsyncSessionLocal() as db:
        try:
            symbols = await _get_watchlist_symbols(db, watchlist_id)
            if not symbols:
                log.info("Forecast scan run %d: no watchlist symbols, skipping", run_id)
                scan_run = await db.get(ScanRun, run_id)
                if scan_run:
                    scan_run.status = ScanRunStatus.COMPLETED
                    scan_run.completed_at = datetime.now(UTC)
                    scan_run.error_message = FORECAST_SCAN_MARKER
                    await db.commit()
                return

            total_forecast = 0
            scanned = 0

            for symbol_id, ticker in symbols:
                try:
                    df = await fetch_ohlcv_for_symbol(symbol_id, ticker, db, TimeframeEnum.D1)
                    if df is None or len(df) < 50:
                        log.info("Forecast %s: insufficient OHLCV data, skipping", ticker)
                        scanned += 1
                        continue

                    result = await asyncio.to_thread(run_forecast, df, ticker, "1d", 20, 50)

                    if result is None:
                        scanned += 1
                        continue

                    forecast_row = ForecastCache(
                        symbol_id=symbol_id,
                        timeframe=result.timeframe,
                        generated_at=datetime.now(UTC),
                        horizon_bars=result.forecast_horizon,
                        last_bar_date=datetime.strptime(
                            result.last_bar_date[:10], "%Y-%m-%d"
                        ).date(),
                        last_close=result.last_close,
                        median=result.median,
                        quantile_10=result.quantile_10,
                        quantile_25=result.quantile_25,
                        quantile_75=result.quantile_75,
                        quantile_90=result.quantile_90,
                        direction=result.direction,
                        direction_confidence=result.direction_confidence,
                        expected_move_pct=result.expected_move_pct,
                    )
                    db.add(forecast_row)
                    await _purge_old_forecasts(db, symbol_id)

                    total_forecast += 1
                    scanned += 1
                    await db.commit()

                except Exception as exc:
                    log.error("Forecast %s failed: %s", ticker, exc)
                    await db.rollback()

            scan_run = await db.get(ScanRun, run_id)
            if scan_run:
                scan_run.status = ScanRunStatus.COMPLETED
                scan_run.completed_at = datetime.now(UTC)
                scan_run.symbols_scanned = len(symbols)
                scan_run.symbols_scored = total_forecast
                scan_run.error_message = FORECAST_SCAN_MARKER
                await db.commit()

            log.info(
                "Forecast scan run %d: completed. symbols=%d, forecast=%d",
                run_id,
                scanned,
                total_forecast,
            )

        except Exception as exc:
            log.error("Forecast scan run %d failed: %s", run_id, exc)
            try:
                scan_run = await db.get(ScanRun, run_id)
                if scan_run:
                    scan_run.status = ScanRunStatus.FAILED
                    scan_run.completed_at = datetime.now(UTC)
                    scan_run.error_message = f"{FORECAST_SCAN_MARKER}: {str(exc)[:1900]}"
                    await db.commit()
            except Exception as commit_exc:
                log.error(
                    "Forecast scan run %d: failed to record error: %s",
                    run_id,
                    commit_exc,
                )
