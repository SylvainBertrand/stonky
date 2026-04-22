"""TA Pre-Scorer API — pre-score tickers for the TA Intraday Claude agent.

Endpoint:
  POST /api/ta/prescore → run pipeline + remap + dedup + filter → JSON

Reference: TC-SWE-95 Phase 1.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.pipeline import fetch_ohlcv_for_symbol, run_analysis_for_ticker
from app.api.ta_service import (
    batch_dedup_check,
    build_scored_ticker,
)
from app.db.session import get_session
from app.ingestion.fetcher import batch_backfill_ohlcv, ensure_symbols
from app.models.enums import TimeframeEnum
from app.schemas.ta import (
    DedupStatus,
    FilteredTicker,
    PrescoreMetadata,
    PrescoreRequest,
    PrescoreResponse,
    ScoredTicker,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ta", tags=["ta-prescorer"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


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

    # Batch-hydrate OHLCV for symbols that have never been fetched.
    # Uses yf.download batch API to stay within caller timeout (~30s).
    backfill_stats = await batch_backfill_ohlcv(
        db, symbol_map, TimeframeEnum.D1, period="1y"
    )
    await db.commit()

    if backfill_stats["hydrated"] > 0:
        log.info(
            "prescore: hydrated %d new tickers (%d failed, %d already cached)",
            backfill_stats["hydrated"],
            backfill_stats["failed"],
            backfill_stats["skipped"],
        )

    missing = [t.upper() for t in body.tickers if t.upper() not in symbol_map]

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

    elapsed_ms = int((time.monotonic() - t0) * 1000)

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
        ),
    )
