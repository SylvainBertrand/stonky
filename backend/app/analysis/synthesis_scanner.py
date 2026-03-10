"""LLM synthesis batch job — runs synthesis for all watchlist symbols.

Runs as a background job (nightly scheduled or manual trigger).
Stores results in the synthesis_results table.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.signal_aggregator import aggregate_signals
from app.analysis.synthesis_agent import SynthesisResult as SynthesisDataclass
from app.analysis.synthesis_agent import synthesize
from app.db.session import AsyncSessionLocal
from app.llm.provider import OllamaProvider, get_provider
from app.models.enums import ScanRunStatus
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.synthesis_result import SynthesisResult
from app.models.watchlists import Watchlist, WatchlistItem

log = logging.getLogger(__name__)

SYNTHESIS_SCAN_MARKER = "llm_synthesis"
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


async def _purge_old_synthesis(db: AsyncSession, symbol_id: int) -> None:
    """Remove synthesis results older than RETENTION_DAYS for a symbol."""
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    await db.execute(
        delete(SynthesisResult).where(
            and_(
                SynthesisResult.symbol_id == symbol_id,
                SynthesisResult.generated_at < cutoff,
            )
        )
    )


async def _store_synthesis_result(
    db: AsyncSession, result: SynthesisDataclass, symbol_id: int
) -> None:
    """Store a synthesis result in the DB."""
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
    await _purge_old_synthesis(db, symbol_id)


async def run_synthesis_scan_all(
    watchlist_id: int | None = None,
    run_id: int | None = None,
) -> None:
    """Run LLM synthesis for all watchlist symbols.

    Parameters
    ----------
    watchlist_id : int | None
        Watchlist to scan; uses default watchlist if None.
    run_id : int | None
        Existing ScanRun ID to use (from API endpoint).
        If None, creates a new ScanRun (for scheduler invocations).
    """
    provider = get_provider()

    # Check Ollama availability before starting
    if isinstance(provider, OllamaProvider):
        if not await provider.is_available():
            log.warning(
                "Synthesis scan: Ollama is not running at %s — skipping synthesis job.",
                provider.base_url,
            )
            return

    async with AsyncSessionLocal() as db:
        if run_id is not None:
            scan_run = await db.get(ScanRun, run_id)
            if scan_run is None:
                log.error("Synthesis scan: ScanRun %d not found", run_id)
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
                error_message=SYNTHESIS_SCAN_MARKER,
            )
            db.add(scan_run)
            await db.flush()
            run_id = scan_run.id
            await db.commit()

        log.info("Synthesis scan run %d: starting", run_id)

    async with AsyncSessionLocal() as db:
        try:
            symbols = await _get_watchlist_symbols(db, watchlist_id)
            if not symbols:
                log.info("Synthesis scan run %d: no watchlist symbols, skipping", run_id)
                scan_run = await db.get(ScanRun, run_id)
                if scan_run:
                    scan_run.status = ScanRunStatus.COMPLETED
                    scan_run.completed_at = datetime.now(UTC)
                    scan_run.error_message = SYNTHESIS_SCAN_MARKER
                    await db.commit()
                return

            total_synthesized = 0

            for symbol_id, ticker in symbols:
                try:
                    signals = await aggregate_signals(ticker, db)
                    if signals is None:
                        log.info("Synthesis %s: no P0 scan data, skipping", ticker)
                        continue

                    result = await synthesize(signals, provider)
                    await _store_synthesis_result(db, result, symbol_id)
                    await db.commit()

                    total_synthesized += 1
                    log.info(
                        "Synthesis %s: %s (%s, %s confidence)",
                        ticker,
                        result.setup_type,
                        result.bias,
                        result.confidence,
                    )

                except Exception as exc:
                    log.error("Synthesis %s failed: %s", ticker, exc)
                    await db.rollback()

            scan_run = await db.get(ScanRun, run_id)
            if scan_run:
                scan_run.status = ScanRunStatus.COMPLETED
                scan_run.completed_at = datetime.now(UTC)
                scan_run.symbols_scanned = len(symbols)
                scan_run.symbols_scored = total_synthesized
                scan_run.error_message = SYNTHESIS_SCAN_MARKER
                await db.commit()

            log.info(
                "Synthesis scan run %d: completed. symbols=%d, synthesized=%d",
                run_id,
                len(symbols),
                total_synthesized,
            )

        except Exception as exc:
            log.error("Synthesis scan run %d failed: %s", run_id, exc)
            try:
                scan_run = await db.get(ScanRun, run_id)
                if scan_run:
                    scan_run.status = ScanRunStatus.FAILED
                    scan_run.completed_at = datetime.now(UTC)
                    scan_run.error_message = (
                        f"{SYNTHESIS_SCAN_MARKER}: {str(exc)[:1900]}"
                    )
                    await db.commit()
            except Exception as commit_exc:
                log.error(
                    "Synthesis scan run %d: failed to record error: %s",
                    run_id,
                    commit_exc,
                )
