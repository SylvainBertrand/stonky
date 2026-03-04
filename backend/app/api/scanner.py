"""
Scanner API — run TA analysis pipeline on watchlist symbols.

Endpoints:
  POST /api/scanner/run               → background scan of all watchlist tickers
  GET  /api/scanner/results           → latest cached results sorted by composite_score
  GET  /api/scanner/results/{symbol}  → full detail for one ticker
  GET  /api/scanner/profiles          → list 4 scanner profiles
  POST /api/scanner/run/{symbol}      → on-demand single-ticker analysis (inline)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.pipeline import (
    AnalysisResult,
    run_analysis_for_ticker,
    run_scanner,
)
from app.analysis.profiles import PROFILES
from app.db.session import AsyncSessionLocal, get_session
from app.models.enums import PatternType, ScanRunStatus, TimeframeEnum
from app.models.indicator_cache import IndicatorCache
from app.models.pattern_detections import PatternDetection
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem
from app.schemas.patterns import PatternDetectionResponse
from app.schemas.scanner import (
    AnalysisMeta,
    AnalysisResponse,
    CategoryScores,
    HarmonicInfo,
    ProfileInfo,
    ScanRunResponse,
    ScanRunStatusResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/scanner", tags=["scanner"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_TF_MAP: dict[str, TimeframeEnum] = {
    "1d": TimeframeEnum.D1,
    "1w": TimeframeEnum.W1,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dict_to_harmonic_info(d: dict | None) -> HarmonicInfo | None:
    """Convert a cached harmonics dict to a HarmonicInfo schema object."""
    if d is None:
        return None
    return HarmonicInfo(
        detected=bool(d.get("detected", False)),
        pattern=d.get("pattern"),
        direction=d.get("direction"),
        ratio_quality=float(d.get("ratio_quality", 0.0)),
        in_prz=bool(d.get("in_prz", False)),
        prz_low=d.get("prz_low"),
        prz_high=d.get("prz_high"),
        bars_since_completion=d.get("bars_since_completion"),
    )


async def _fetch_chart_patterns_bulk(
    db: AsyncSession,
    symbol_ids: set[int],
    timeframe: TimeframeEnum,
) -> dict[int, list[PatternDetectionResponse]]:
    """Fetch latest YOLO chart pattern detections for multiple symbols at once."""
    if not symbol_ids:
        return {}

    result = await db.execute(
        select(PatternDetection)
        .where(
            PatternDetection.symbol_id.in_(symbol_ids),
            PatternDetection.timeframe == timeframe,
            PatternDetection.pattern_type == PatternType.CHART_GEOMETRIC,
        )
        .order_by(desc(PatternDetection.detected_at), desc(PatternDetection.confidence))
    )
    rows = result.scalars().all()

    # Group by symbol_id, keep only detections from the most recent scan per symbol
    by_symbol: dict[int, list[PatternDetectionResponse]] = {}
    latest_date_per_symbol: dict[int, object] = {}

    for row in rows:
        sid = row.symbol_id
        det_date = row.detected_at.date() if row.detected_at else None

        if sid not in latest_date_per_symbol:
            latest_date_per_symbol[sid] = det_date

        # Only include detections from the most recent scan date
        if det_date != latest_date_per_symbol[sid]:
            continue

        geometry = row.geometry or {}
        if sid not in by_symbol:
            by_symbol[sid] = []
        by_symbol[sid].append(
            PatternDetectionResponse(
                pattern=row.pattern_name,
                direction=row.direction.value,
                confidence=float(row.confidence),
                bar_start=geometry.get("bar_start", 0),
                bar_end=geometry.get("bar_end", 0),
            )
        )

    return by_symbol


def _result_to_response(
    result: AnalysisResult,
    scanned_at: str = "",
    chart_patterns: list[PatternDetectionResponse] | None = None,
) -> AnalysisResponse:
    meta = result.meta
    return AnalysisResponse(
        symbol=result.symbol,
        scanned_at=scanned_at or datetime.now(timezone.utc).isoformat(),
        composite_score=result.composite_score,
        category_scores=CategoryScores(**result.category_scores),
        profile_matches=result.profile_matches,
        signals=result.signals,
        meta=AnalysisMeta(
            atr=meta.get("atr", 0.0),
            atr_pct=meta.get("atr_pct", 0.0),
            last_price=meta.get("last_price", 0.0),
            volume_ratio=float(meta.get("volume_ratio", 0.0)),
            price_change_pct=float(meta.get("price_change_pct", 0.0)),
            timestamp=str(meta.get("timestamp", "")),
            bars=int(meta.get("bars", 0)),
        ),
        harmonics=_dict_to_harmonic_info(result.harmonics),
        chart_patterns=chart_patterns or [],
        is_actionable=result.is_actionable,
        volume_contradiction=result.volume_contradiction,
    )


def _normalize_profile_name(raw: str) -> str:
    """Normalize profile name: snake_case or CamelCase → CamelCase registry key."""
    # If it already looks CamelCase (contains uppercase), return as-is
    if any(c.isupper() for c in raw):
        return raw
    # Convert snake_case to CamelCase
    return "".join(word.capitalize() for word in re.split(r"[_\-]", raw))


async def _get_watchlist_symbols(
    db: AsyncSession, watchlist_id: int | None = None
) -> list[tuple[int, str]]:
    """Return (symbol_id, ticker) pairs for the given watchlist.

    When watchlist_id is None, uses the active (is_default=True) watchlist.
    """
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
    symbols = [(row[0], row[1]) for row in result.all()]
    log.info(
        "Resolved watchlist symbols: watchlist_id=%s, count=%d, sample=%s",
        watchlist_id,
        len(symbols),
        [ticker for _, ticker in symbols[:10]],
    )
    return symbols


async def _run_scanner_bg(run_id: int, watchlist_id: int | None = None) -> None:
    """Background task: run scanner for watchlist symbols, tracking status in scan_runs."""
    async with AsyncSessionLocal() as db:
        # Mark as running
        try:
            scan_run = await db.get(ScanRun, run_id)
            if scan_run is None:
                log.error("Scanner background task: scan_run %d not found", run_id)
                return
            scan_run.status = ScanRunStatus.RUNNING
            scan_run.started_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as exc:
            log.error("Scanner run %d: failed to mark as running: %s", run_id, exc)
            return

        # Execute
        try:
            symbols = await _get_watchlist_symbols(db, watchlist_id)
            log.info(
                "Scanner run %d start: watchlist_id=%s, symbol_count=%d",
                run_id,
                watchlist_id,
                len(symbols),
            )
            if not symbols:
                log.info("Scanner run %d: no symbols found", run_id)
                scan_run.status = ScanRunStatus.COMPLETED
                scan_run.completed_at = datetime.now(timezone.utc)
                scan_run.symbols_scored = 0
                await db.commit()
                return

            results = await run_scanner(symbols)
            scan_run.status = ScanRunStatus.COMPLETED
            scan_run.completed_at = datetime.now(timezone.utc)
            scan_run.symbols_scored = len(results)
            await db.commit()
            log.info(
                "Scanner run %d: completed %d symbols, scored %d, top=%s",
                run_id, len(symbols), len(results),
                [
                    {
                        "symbol": r.symbol,
                        "score": round(r.composite_score, 4),
                        "profiles": r.profile_matches,
                    }
                    for r in results[:5]
                ],
            )
        except Exception as exc:
            log.error("Scanner run %d failed: %s", run_id, exc)
            try:
                scan_run.status = ScanRunStatus.FAILED
                scan_run.completed_at = datetime.now(timezone.utc)
                scan_run.error_message = str(exc)[:2000]
                await db.commit()
            except Exception as commit_exc:
                log.error("Scanner run %d: failed to record error: %s", run_id, commit_exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/run", response_model=ScanRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_scan(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    watchlist_id: Annotated[int | None, Query(description="Watchlist to scan; defaults to active watchlist")] = None,
) -> ScanRunResponse:
    """Trigger a full scan of watchlist symbols (background task).

    Returns a run_id (integer) you can poll via GET /scanner/runs/{run_id}.
    Scans the active (is_default) watchlist by default; pass ?watchlist_id= to override.
    """
    symbols = await _get_watchlist_symbols(session, watchlist_id)
    if not symbols:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No symbols in watchlist. Add tickers to a watchlist first.",
        )

    # Create a scan_run record immediately so the caller can poll its status
    scan_run = ScanRun(
        profile_id=None,
        watchlist_id=watchlist_id,
        status=ScanRunStatus.PENDING,
        symbols_scanned=len(symbols),
        symbols_scored=0,
    )
    session.add(scan_run)
    await session.flush()   # get the auto-assigned id
    run_id = scan_run.id
    await session.commit()

    log.info(
        "Queued scan run %d: watchlist_id=%s, symbols=%d",
        run_id,
        watchlist_id,
        len(symbols),
    )

    background_tasks.add_task(_run_scanner_bg, run_id, watchlist_id)
    return ScanRunResponse(
        run_id=run_id,
        status="queued",
        symbols_queued=len(symbols),
    )


@router.get("/runs/{run_id}", response_model=ScanRunStatusResponse)
async def get_run_status(
    run_id: int,
    session: SessionDep,
) -> ScanRunStatusResponse:
    """Return the status of a scan run started via POST /scanner/run."""
    scan_run = await session.get(ScanRun, run_id)
    if scan_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan run {run_id} not found",
        )
    return ScanRunStatusResponse(
        run_id=scan_run.id,
        status=scan_run.status.value,
        started_at=scan_run.started_at.isoformat() if scan_run.started_at else None,
        completed_at=scan_run.completed_at.isoformat() if scan_run.completed_at else None,
        error_message=scan_run.error_message,
        symbols_scanned=scan_run.symbols_scanned or 0,
        symbols_scored=scan_run.symbols_scored or 0,
    )


@router.get("/results", response_model=list[AnalysisResponse])
async def get_latest_results(
    session: SessionDep,
    profile: Annotated[
        str | None,
        Query(description="Filter by profile name (e.g. momentum_breakout or MomentumBreakout)"),
    ] = None,
    timeframe: Annotated[str, Query(description="Timeframe: 1d or 1w")] = "1d",
    watchlist_id: Annotated[int | None, Query(description="Limit results to symbols in this watchlist")] = None,
) -> list[AnalysisResponse]:
    """Return latest cached analysis results sorted by composite_score descending.

    Use ?profile= to filter by matching profile name (case-insensitive, snake_case or CamelCase).
    Use ?timeframe= to select which timeframe's analysis to return (default: 1d).
    Use ?watchlist_id= to limit results to symbols belonging to a specific watchlist.
    """
    tf_enum = _TF_MAP.get(timeframe, TimeframeEnum.D1)

    # Resolve watchlist symbol IDs for filtering when requested
    watchlist_symbol_ids: set[int] | None = None
    if watchlist_id is not None:
        wl_rows = await session.execute(
            select(WatchlistItem.symbol_id).where(WatchlistItem.watchlist_id == watchlist_id)
        )
        watchlist_symbol_ids = {row[0] for row in wl_rows.all()}
        log.info(
            "Results query: timeframe=%s, watchlist_id=%s, watchlist_symbol_count=%d, profile=%s",
            tf_enum.value,
            watchlist_id,
            len(watchlist_symbol_ids),
            profile,
        )
    else:
        log.info(
            "Results query: timeframe=%s, watchlist_id=None, profile=%s",
            tf_enum.value,
            profile,
        )

    # Get latest full_analysis entry per symbol for the requested timeframe
    result = await session.execute(
        select(IndicatorCache)
        .where(
            IndicatorCache.indicator_name == "full_analysis",
            IndicatorCache.timeframe == tf_enum,
        )
        .order_by(desc(IndicatorCache.time))
    )
    rows = result.scalars().all()
    log.info("Results query raw rows: %d", len(rows))

    # Deduplicate: keep latest per symbol_id, optionally scoped to watchlist
    seen: set[int] = set()
    unique: list[IndicatorCache] = []
    for row in rows:
        if row.symbol_id not in seen:
            if watchlist_symbol_ids is None or row.symbol_id in watchlist_symbol_ids:
                seen.add(row.symbol_id)
                unique.append(row)

    log.info("Results query unique rows after dedupe/filter: %d", len(unique))

    # Fetch chart patterns in bulk for all result symbols
    all_symbol_ids = {row.symbol_id for row in unique}
    patterns_by_symbol = await _fetch_chart_patterns_bulk(session, all_symbol_ids, tf_enum)

    # Parse
    responses: list[AnalysisResponse] = []
    for row in unique:
        try:
            val = row.value
            if not isinstance(val, dict):
                continue
            meta_raw = val.get("meta", {})
            responses.append(
                AnalysisResponse(
                    symbol=str(val.get("symbol", "")),
                    scanned_at=row.time.isoformat(),
                    composite_score=float(val.get("composite_score", 0.0)),
                    category_scores=CategoryScores(**val.get("category_scores", {})),
                    profile_matches=val.get("profile_matches", []),
                    signals=val.get("signals", {}),
                    meta=AnalysisMeta(
                        atr=float(meta_raw.get("atr", 0.0)),
                        atr_pct=float(meta_raw.get("atr_pct", 0.0)),
                        last_price=float(meta_raw.get("last_price", 0.0)),
                        volume_ratio=float(meta_raw.get("volume_ratio", 0.0)),
                        price_change_pct=float(meta_raw.get("price_change_pct", 0.0)),
                        timestamp=str(meta_raw.get("timestamp", "")),
                        bars=int(meta_raw.get("bars", 0)),
                    ),
                    harmonics=_dict_to_harmonic_info(val.get("harmonics")),
                    chart_patterns=patterns_by_symbol.get(row.symbol_id, []),
                    is_actionable=bool(val.get("is_actionable", False)),
                    volume_contradiction=bool(val.get("volume_contradiction", False)),
                )
            )
        except Exception as exc:
            log.warning("Failed to parse cached result: %s", exc)

    # Sort by composite score descending
    responses.sort(key=lambda r: r.composite_score, reverse=True)

    pre_profile_count = len(responses)

    # Filter by profile if requested
    if profile:
        canonical = _normalize_profile_name(profile)
        profile_counts: dict[str, int] = {}
        for resp in responses:
            for matched in resp.profile_matches:
                profile_counts[matched] = profile_counts.get(matched, 0) + 1
        responses = [r for r in responses if canonical in r.profile_matches]
        log.info(
            "Results profile filter: requested=%s canonical=%s before=%d after=%d counts=%s",
            profile,
            canonical,
            pre_profile_count,
            len(responses),
            profile_counts,
        )

    # Assign rank (1 = highest composite score)
    for i, resp in enumerate(responses):
        resp.rank = i + 1

    log.info(
        "Results response: count=%d top=%s",
        len(responses),
        [
            {
                "symbol": r.symbol,
                "score": round(r.composite_score, 4),
                "profiles": r.profile_matches,
            }
            for r in responses[:5]
        ],
    )

    return responses


@router.get("/results/{symbol}", response_model=AnalysisResponse)
async def get_symbol_result(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="Timeframe: 1d or 1w")] = "1d",
) -> AnalysisResponse:
    """Return full analysis detail for a single ticker."""
    tf_enum = _TF_MAP.get(timeframe, TimeframeEnum.D1)

    # Resolve symbol_id
    sym_result = await session.execute(
        select(Symbol.id).where(Symbol.ticker == symbol.upper())
    )
    symbol_id = sym_result.scalar_one_or_none()
    if symbol_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Symbol {symbol} not found")

    cache_result = await session.execute(
        select(IndicatorCache)
        .where(
            IndicatorCache.symbol_id == symbol_id,
            IndicatorCache.indicator_name == "full_analysis",
            IndicatorCache.timeframe == tf_enum,
        )
        .order_by(desc(IndicatorCache.time))
        .limit(1)
    )
    row = cache_result.scalar_one_or_none()

    # Fetch chart patterns for this symbol
    patterns_map = await _fetch_chart_patterns_bulk(session, {symbol_id}, tf_enum)
    symbol_patterns = patterns_map.get(symbol_id, [])

    # Auto-run analysis when no cache exists (e.g. first weekly request)
    if row is None:
        result = await run_analysis_for_ticker(
            symbol_id, symbol.upper(), session, timeframe=tf_enum
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No {timeframe} OHLCV data for {symbol}. Trigger a data refresh first.",
            )
        await session.commit()
        return _result_to_response(result, chart_patterns=symbol_patterns)

    val = row.value
    meta_raw = val.get("meta", {})
    return AnalysisResponse(
        symbol=str(val.get("symbol", "")),
        scanned_at=row.time.isoformat(),
        composite_score=float(val.get("composite_score", 0.0)),
        category_scores=CategoryScores(**val.get("category_scores", {})),
        profile_matches=val.get("profile_matches", []),
        signals=val.get("signals", {}),
        meta=AnalysisMeta(
            atr=float(meta_raw.get("atr", 0.0)),
            atr_pct=float(meta_raw.get("atr_pct", 0.0)),
            last_price=float(meta_raw.get("last_price", 0.0)),
            volume_ratio=float(meta_raw.get("volume_ratio", 0.0)),
            price_change_pct=float(meta_raw.get("price_change_pct", 0.0)),
            timestamp=str(meta_raw.get("timestamp", "")),
            bars=int(meta_raw.get("bars", 0)),
        ),
        harmonics=_dict_to_harmonic_info(val.get("harmonics")),
        chart_patterns=symbol_patterns,
        is_actionable=bool(val.get("is_actionable", False)),
        volume_contradiction=bool(val.get("volume_contradiction", False)),
    )


@router.get("/profiles", response_model=list[ProfileInfo])
async def list_profiles() -> list[ProfileInfo]:
    """List all scanner profiles with their configurations."""
    return [
        ProfileInfo(
            name=p.name,
            description=p.description,
            score_threshold=p.score_threshold,
            required_conditions=p.required_conditions,
        )
        for p in PROFILES.values()
    ]


@router.post("/run/{symbol}", response_model=AnalysisResponse)
async def run_symbol_analysis(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="Timeframe: 1d or 1w")] = "1d",
) -> AnalysisResponse:
    """Run on-demand analysis for a single ticker (inline, returns immediately)."""
    tf_enum = _TF_MAP.get(timeframe, TimeframeEnum.D1)

    sym_result = await session.execute(
        select(Symbol).where(Symbol.ticker == symbol.upper())
    )
    sym = sym_result.scalar_one_or_none()
    if sym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Symbol {symbol} not found")

    result = await run_analysis_for_ticker(sym.id, sym.ticker, session, timeframe=tf_enum)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient {timeframe} OHLCV data for {symbol}. Trigger a data refresh first.",
        )

    await session.commit()
    return _result_to_response(result)
