"""Parallelized nightly analysis pipeline.

Runs YOLO → Chronos → signal aggregation → LLM synthesis for each symbol,
with K symbols running concurrently.  Semaphores bound concurrency per step
to avoid resource contention (GPU for YOLO, CPU for Chronos, Ollama serialized).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import ScanRunStatus
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem
from app.scheduler.progress import (
    mark_pipeline_done,
    mark_symbol_done,
    mark_symbol_started,
    reset_progress,
)

log = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    yolo_concurrency: int = 4  # YOLO: CPU/GPU-bound (chart render + inference)
    chronos_concurrency: int = 4  # Chronos: CPU-bound (model inference)
    synthesis_concurrency: int = 1  # Ollama: single-threaded, do not increase


# Module-level semaphores — created lazily to avoid issues at import time
_chronos_semaphore: asyncio.Semaphore | None = None
_ollama_semaphore: asyncio.Semaphore | None = None


def _get_chronos_semaphore(limit: int) -> asyncio.Semaphore:
    global _chronos_semaphore
    if _chronos_semaphore is None or _chronos_semaphore._value != limit:
        _chronos_semaphore = asyncio.Semaphore(limit)
    return _chronos_semaphore


def _get_ollama_semaphore(limit: int) -> asyncio.Semaphore:
    global _ollama_semaphore
    if _ollama_semaphore is None or _ollama_semaphore._value != limit:
        _ollama_semaphore = asyncio.Semaphore(limit)
    return _ollama_semaphore


async def get_watchlist_symbols(
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


async def _run_yolo_for_symbol(
    symbol_id: int, ticker: str, scan_run_id: int, db: AsyncSession
) -> None:
    """Run YOLO chart pattern scan for one symbol."""
    from app.analysis.yolo_scanner import run_yolo_scan_symbol

    await run_yolo_scan_symbol(symbol_id, ticker, scan_run_id, db)
    await db.commit()


async def _run_chronos_for_symbol(
    symbol_id: int,
    ticker: str,
    db: AsyncSession,
    semaphore: asyncio.Semaphore,
) -> None:
    """Run Chronos forecast for one symbol, bounded by semaphore."""
    import asyncio as _asyncio
    from datetime import timedelta

    from sqlalchemy import and_, delete

    from app.analysis.forecaster import run_forecast
    from app.analysis.pipeline import fetch_ohlcv_for_symbol
    from app.models.enums import TimeframeEnum
    from app.models.forecast_cache import ForecastCache

    async with semaphore:
        df = await fetch_ohlcv_for_symbol(symbol_id, ticker, db, TimeframeEnum.D1)
        if df is None or len(df) < 50:
            log.info("Pipeline Chronos %s: insufficient data, skipping", ticker)
            return

        result = await _asyncio.to_thread(run_forecast, df, ticker, "1d", 20, 50)
        if result is None:
            return

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

        # Purge old forecasts
        cutoff = datetime.now(UTC) - timedelta(days=7)
        await db.execute(
            delete(ForecastCache).where(
                and_(
                    ForecastCache.symbol_id == symbol_id,
                    ForecastCache.generated_at < cutoff,
                )
            )
        )
        await db.commit()


async def _run_synthesis_for_symbol(
    symbol_id: int,
    ticker: str,
    db: AsyncSession,
    semaphore: asyncio.Semaphore,
) -> None:
    """Run LLM synthesis for one symbol, bounded by semaphore.

    Signal aggregation happens BEFORE acquiring the semaphore so that DB
    reads are pipelined while Ollama is busy with the previous symbol.
    """
    from datetime import timedelta

    from sqlalchemy import and_, delete

    from app.analysis.signal_aggregator import aggregate_signals
    from app.analysis.synthesis_agent import SynthesisResult as SynthesisDataclass
    from app.analysis.synthesis_agent import synthesize
    from app.llm.provider import get_provider
    from app.models.synthesis_result import SynthesisResult

    # Aggregate signals outside the semaphore (DB reads, fast)
    signals = await aggregate_signals(ticker, db)
    if signals is None:
        log.info("Pipeline synthesis %s: no P0 scan data, skipping", ticker)
        return

    provider = get_provider()

    # Acquire Ollama semaphore — only one LLM call at a time
    async with semaphore:
        result = await synthesize(signals, provider)

        row = SynthesisResult(
            symbol_id=symbol_id,
            generated_at=datetime.fromisoformat(result.generated_at),
            setup_type=result.setup_type[:50],
            bias=result.bias[:10],
            confidence=result.confidence[:10],
            summary=result.summary,
            signal_confluence=result.signal_confluence,
            signal_conflicts=result.signal_conflicts,
            entry=result.entry,
            stop=result.stop,
            target=result.target,
            risk_reward=result.risk_reward,
            key_risk=result.key_risk,
            parse_error=result.parse_error,
            raw_response=result.raw_response[:5000] if result.raw_response else None,
        )
        db.add(row)

        # Purge old synthesis
        cutoff = datetime.now(UTC) - timedelta(days=7)
        await db.execute(
            delete(SynthesisResult).where(
                and_(
                    SynthesisResult.symbol_id == symbol_id,
                    SynthesisResult.generated_at < cutoff,
                )
            )
        )
        await db.commit()

    log.info(
        "Pipeline synthesis %s: %s (%s, %s confidence)",
        ticker,
        result.setup_type,
        result.bias,
        result.confidence,
    )


async def _run_symbol_pipeline(
    symbol_id: int,
    ticker: str,
    scan_run_id: int,
    outer_semaphore: asyncio.Semaphore,
    chronos_semaphore: asyncio.Semaphore,
    ollama_semaphore: asyncio.Semaphore,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Full pipeline for one symbol.  Uses its own DB session."""
    async with outer_semaphore:
        mark_symbol_started(ticker)
        try:
            async with session_factory() as db:
                # Step 1: YOLO chart pattern scan
                try:
                    await _run_yolo_for_symbol(symbol_id, ticker, scan_run_id, db)
                except Exception as exc:
                    log.error("Pipeline YOLO %s failed: %s", ticker, exc)
                    await db.rollback()

                # Step 2: Chronos forecast
                try:
                    await _run_chronos_for_symbol(
                        symbol_id, ticker, db, chronos_semaphore
                    )
                except Exception as exc:
                    log.error("Pipeline Chronos %s failed: %s", ticker, exc)
                    await db.rollback()

                # Step 3: LLM synthesis (signal aggregation + Ollama)
                try:
                    await _run_synthesis_for_symbol(
                        symbol_id, ticker, db, ollama_semaphore
                    )
                except Exception as exc:
                    log.error("Pipeline synthesis %s failed: %s", ticker, exc)
                    await db.rollback()

            mark_symbol_done(ticker, success=True)
        except Exception as exc:
            log.error("Pipeline failed for %s: %s", ticker, exc, exc_info=True)
            mark_symbol_done(ticker, success=False)


async def run_full_pipeline(
    symbols: list[tuple[int, str]],
    config: PipelineConfig,
    session_factory: async_sessionmaker[AsyncSession],
    scan_run_id: int,
) -> dict[str, int | float]:
    """Run the full analysis pipeline for all symbols.

    Returns ``{completed, failed, duration_s}``.
    """
    reset_progress(len(symbols))
    start = time.monotonic()

    outer_semaphore = asyncio.Semaphore(config.yolo_concurrency)
    chronos_semaphore = _get_chronos_semaphore(config.chronos_concurrency)
    ollama_semaphore = _get_ollama_semaphore(config.synthesis_concurrency)

    tasks = [
        _run_symbol_pipeline(
            sym_id,
            ticker,
            scan_run_id,
            outer_semaphore,
            chronos_semaphore,
            ollama_semaphore,
            session_factory,
        )
        for sym_id, ticker in symbols
    ]

    await asyncio.gather(*tasks, return_exceptions=True)

    duration = round(time.monotonic() - start, 1)
    from app.scheduler.progress import get_progress

    progress = get_progress()
    success = progress.failed == 0
    mark_pipeline_done(success=success)

    return {
        "completed": progress.completed,
        "failed": progress.failed,
        "duration_s": duration,
    }
