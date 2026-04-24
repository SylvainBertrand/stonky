"""TA Pre-Scorer API — pre-score tickers for the TA Intraday Claude agent.

Endpoints:
  POST /api/ta/prescore → run pipeline + remap + dedup + filter → JSON
  POST /api/ta/hydrate  → async pre-warm symbols + OHLCV (TC-SWE-102)

Reference: TC-SWE-95 Phase 1, TC-SWE-102.
"""

from __future__ import annotations

import collections
import logging
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.pipeline import fetch_ohlcv_for_symbol, run_analysis_for_ticker
from app.api.ta_service import (
    batch_dedup_check,
    build_scored_ticker,
)
from app.db.session import AsyncSessionLocal, get_session
from app.ingestion.fetcher import batch_backfill_ohlcv, ensure_symbols
from app.models.enums import TimeframeEnum
from app.schemas.ta import (
    DedupStatus,
    FilteredTicker,
    HydrateRequest,
    HydrateResponse,
    PrescoreMetadata,
    PrescoreRequest,
    PrescoreResponse,
    ScoredTicker,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ta", tags=["ta-prescorer"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# Filter reason keys (canonical strings for aggregation)
# ---------------------------------------------------------------------------

_REASON_NOT_IN_DB = "not_in_db"
_REASON_INSUFFICIENT_OHLCV = "insufficient_ohlcv"
_REASON_OHLCV_FETCH_FAILED = "ohlcv_fetch_failed"
_REASON_BELOW_THRESHOLD = "below_threshold"
_REASON_DEDUP = "dedup"


def _classify_filter_reason(reason: str) -> str:
    """Map a human-readable filter reason to a canonical key."""
    if "not in Stonky DB" in reason:
        return _REASON_NOT_IN_DB
    if "insufficient OHLCV" in reason:
        return _REASON_INSUFFICIENT_OHLCV
    if "OHLCV fetch failed" in reason:
        return _REASON_OHLCV_FETCH_FAILED
    if "below threshold" in reason:
        return _REASON_BELOW_THRESHOLD
    if "dedup" in reason:
        return _REASON_DEDUP
    return reason


@router.post("/prescore", response_model=PrescoreResponse)
async def prescore(body: PrescoreRequest, db: SessionDep) -> PrescoreResponse:
    """Pre-score tickers for the TA Intraday Claude agent.

    Runs the existing Stonky analysis pipeline per ticker, remaps to
    4-category TA weights (0-10 scale), classifies patterns, computes
    candidate levels, checks dedup against Signal Registry, filters
    by score threshold, and generates notes for Claude.
    """
    t0 = time.monotonic()
    scan_ts = datetime.now(UTC).isoformat()

    # Auto-create Symbol records for unknown tickers (concurrency-safe upsert).
    # This ensures screener tickers not on the watchlist get registered.
    symbol_map = await ensure_symbols(db, body.tickers)
    await db.commit()

    log.info(
        "prescore: %d tickers submitted, %d symbols resolved (first 5: %s)",
        len(body.tickers),
        len(symbol_map),
        list(symbol_map.keys())[:5],
    )

    # Batch-hydrate OHLCV for symbols that have never been fetched.
    # Uses yf.download batch API to stay within caller timeout (~30s).
    backfill_stats = await batch_backfill_ohlcv(db, symbol_map, TimeframeEnum.D1, period="1y")
    await db.commit()

    log.info(
        "prescore: backfill hydrated=%d failed=%d skipped=%d",
        backfill_stats["hydrated"],
        backfill_stats["failed"],
        backfill_stats["skipped"],
    )

    missing = [t.upper() for t in body.tickers if t.upper() not in symbol_map]

    if missing:
        log.warning(
            "prescore: %d/%d tickers not in symbol_map after ensure_symbols "
            "(first 5: %s). This should not happen — investigate DB state.",
            len(missing),
            len(body.tickers),
            missing[:5],
        )

    # Batch dedup query (single Notion call for all tickers)
    dedup_map = await batch_dedup_check(body.tickers, body.dedup_lookback_hours)

    # Run pipeline per ticker
    scored: list[ScoredTicker] = []
    filtered_out: list[FilteredTicker] = []
    tickers_filtered_dedup = 0

    for ticker in body.tickers:
        upper_ticker = ticker.upper()
        if upper_ticker not in symbol_map:
            filtered_out.append(FilteredTicker(ticker=ticker, reason="ticker not in Stonky DB"))
            continue

        symbol_id = symbol_map[upper_ticker]

        # Run analysis
        result = await run_analysis_for_ticker(symbol_id, ticker, db, TimeframeEnum.D1)
        if result is None:
            filtered_out.append(FilteredTicker(ticker=ticker, reason="insufficient OHLCV data"))
            continue

        # Fetch DataFrame again for raw indicator extraction
        df = await fetch_ohlcv_for_symbol(symbol_id, ticker, db, TimeframeEnum.D1)
        if df is None:
            filtered_out.append(FilteredTicker(ticker=ticker, reason="OHLCV fetch failed"))
            continue

        dedup = dedup_map.get(ticker)
        if dedup is None:
            dedup = DedupStatus()

        ticker_result = build_scored_ticker(result, df, dedup)

        # Threshold filter
        if ticker_result.composite_score < body.score_threshold:
            filtered_out.append(
                FilteredTicker(
                    ticker=ticker,
                    reason=(
                        f"composite_score {ticker_result.composite_score:.1f} "
                        f"below threshold {body.score_threshold}"
                    ),
                )
            )
            continue

        # Dedup filter (filing_recommended=false → filtered_out)
        if not ticker_result.dedup_status.filing_recommended:
            filtered_out.append(
                FilteredTicker(
                    ticker=ticker,
                    reason=ticker_result.dedup_status.skip_reason or "dedup filtered",
                )
            )
            tickers_filtered_dedup += 1
            continue

        scored.append(ticker_result)

    # Sort by composite descending
    scored.sort(key=lambda s: s.composite_score, reverse=True)

    # TC-SWE-102: Compute filter reason breakdown for diagnostics
    reason_counts: dict[str, int] = dict(
        collections.Counter(_classify_filter_reason(f.reason) for f in filtered_out)
    )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    log.info(
        "prescore: scored=%d filtered=%d reasons=%s latency=%dms",
        len(scored),
        len(filtered_out),
        reason_counts,
        elapsed_ms,
    )

    return PrescoreResponse(
        schema_version="1.0.0",
        scan_timestamp=scan_ts,
        tickers=scored,
        filtered_out=filtered_out,
        metadata=PrescoreMetadata(
            tickers_input=len(body.tickers),
            tickers_scored=len(scored) + len(filtered_out) - len(missing),
            tickers_above_threshold=len(scored),
            tickers_filtered_dedup=tickers_filtered_dedup,
            stonky_pipeline_latency_ms=elapsed_ms,
            symbols_resolved=len(symbol_map),
            filter_reasons=reason_counts,
            backfill_stats=backfill_stats,
        ),
    )


# ---------------------------------------------------------------------------
# Hydrate endpoint — async pre-warm (TC-SWE-102)
# ---------------------------------------------------------------------------


async def _hydrate_bg(tickers: list[str]) -> None:
    """Background task: ensure symbols exist and OHLCV data is available."""
    async with AsyncSessionLocal() as session:
        symbol_map = await ensure_symbols(session, tickers)
        await session.commit()

        stats = await batch_backfill_ohlcv(session, symbol_map, TimeframeEnum.D1, period="1y")
        await session.commit()

        log.info(
            "hydrate_bg: %d tickers → %d symbols, hydrated=%d failed=%d skipped=%d",
            len(tickers),
            len(symbol_map),
            stats["hydrated"],
            stats["failed"],
            stats["skipped"],
        )


@router.post("/hydrate", response_model=HydrateResponse)
async def hydrate(body: HydrateRequest, background_tasks: BackgroundTasks) -> HydrateResponse:
    """Pre-warm Symbol records and OHLCV data for a batch of tickers.

    Returns immediately; hydration runs in the background. Call this
    from WF17 (tier2-screen) after writing survivors to the Daily Screener
    DB, so that WF01 prescore finds data already cached.
    """
    background_tasks.add_task(_hydrate_bg, body.tickers)
    log.info("hydrate: queued %d tickers for background hydration", len(body.tickers))
    return HydrateResponse(tickers_submitted=len(body.tickers))
