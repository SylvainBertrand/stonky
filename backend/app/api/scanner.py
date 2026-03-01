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
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.pipeline import (
    AnalysisResult,
    run_analysis_for_ticker,
    run_scanner,
)
from app.analysis.profiles import PROFILES
from app.db.session import AsyncSessionLocal, get_session
from app.models.enums import TimeframeEnum
from app.models.indicator_cache import IndicatorCache
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem
from app.schemas.scanner import (
    AnalysisMeta,
    AnalysisResponse,
    CategoryScores,
    HarmonicInfo,
    ProfileInfo,
    ScanRunResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/scanner", tags=["scanner"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


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


def _result_to_response(result: AnalysisResult) -> AnalysisResponse:
    meta = result.meta
    return AnalysisResponse(
        symbol=result.symbol,
        composite_score=result.composite_score,
        category_scores=CategoryScores(**result.category_scores),
        profile_matches=result.profile_matches,
        signals=result.signals,
        meta=AnalysisMeta(
            atr=meta.get("atr", 0.0),
            atr_pct=meta.get("atr_pct", 0.0),
            last_price=meta.get("last_price", 0.0),
            timestamp=str(meta.get("timestamp", "")),
            bars=int(meta.get("bars", 0)),
        ),
        harmonics=_dict_to_harmonic_info(result.harmonics),
    )


async def _get_all_watchlist_symbols(db: AsyncSession) -> list[tuple[int, str]]:
    """Return all (symbol_id, ticker) pairs across all watchlists."""
    result = await db.execute(
        select(Symbol.id, Symbol.ticker)
        .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
        .where(Symbol.is_active.is_(True))
        .distinct()
    )
    return [(row[0], row[1]) for row in result.all()]


async def _run_scanner_bg(run_id: str) -> None:
    """Background task: run scanner for all watchlist symbols."""
    async with AsyncSessionLocal() as db:
        try:
            symbols = await _get_all_watchlist_symbols(db)
            if not symbols:
                log.info("Scanner run %s: no symbols found", run_id)
                return
            results = await run_scanner(symbols, db)
            await db.commit()
            log.info(
                "Scanner run %s: completed %d symbols, cached %d results",
                run_id, len(symbols), len(results),
            )
        except Exception as exc:
            log.error("Scanner run %s failed: %s", run_id, exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/run", response_model=dict[str, Any])
async def trigger_scan(
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> dict[str, Any]:
    """Trigger a full scan of all watchlist symbols (background task)."""
    symbols = await _get_all_watchlist_symbols(session)
    run_id = str(uuid.uuid4())
    background_tasks.add_task(_run_scanner_bg, run_id)
    return {
        "run_id": run_id,
        "status": "queued",
        "symbols_queued": len(symbols),
    }


@router.get("/results", response_model=list[AnalysisResponse])
async def get_latest_results(session: SessionDep) -> list[AnalysisResponse]:
    """Return latest cached analysis results sorted by composite_score descending."""
    # Get latest full_analysis entry per symbol
    result = await session.execute(
        select(IndicatorCache)
        .where(IndicatorCache.indicator_name == "full_analysis")
        .order_by(desc(IndicatorCache.time))
    )
    rows = result.scalars().all()

    # Deduplicate: keep latest per (symbol_id, timeframe)
    seen: set[tuple[int, str]] = set()
    unique: list[IndicatorCache] = []
    for row in rows:
        key = (row.symbol_id, row.timeframe.value)
        if key not in seen:
            seen.add(key)
            unique.append(row)

    # Parse and sort
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
                    composite_score=float(val.get("composite_score", 0.0)),
                    category_scores=CategoryScores(**val.get("category_scores", {})),
                    profile_matches=val.get("profile_matches", []),
                    signals=val.get("signals", {}),
                    meta=AnalysisMeta(
                        atr=float(meta_raw.get("atr", 0.0)),
                        atr_pct=float(meta_raw.get("atr_pct", 0.0)),
                        last_price=float(meta_raw.get("last_price", 0.0)),
                        timestamp=str(meta_raw.get("timestamp", "")),
                        bars=int(meta_raw.get("bars", 0)),
                    ),
                    harmonics=_dict_to_harmonic_info(val.get("harmonics")),
                )
            )
        except Exception as exc:
            log.warning("Failed to parse cached result: %s", exc)

    responses.sort(key=lambda r: r.composite_score, reverse=True)
    return responses


@router.get("/results/{symbol}", response_model=AnalysisResponse)
async def get_symbol_result(symbol: str, session: SessionDep) -> AnalysisResponse:
    """Return full analysis detail for a single ticker."""
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
        )
        .order_by(desc(IndicatorCache.time))
        .limit(1)
    )
    row = cache_result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No cached analysis for {symbol}. Run /scanner/run/{symbol} first.",
        )

    val = row.value
    meta_raw = val.get("meta", {})
    return AnalysisResponse(
        symbol=str(val.get("symbol", "")),
        composite_score=float(val.get("composite_score", 0.0)),
        category_scores=CategoryScores(**val.get("category_scores", {})),
        profile_matches=val.get("profile_matches", []),
        signals=val.get("signals", {}),
        meta=AnalysisMeta(
            atr=float(meta_raw.get("atr", 0.0)),
            atr_pct=float(meta_raw.get("atr_pct", 0.0)),
            last_price=float(meta_raw.get("last_price", 0.0)),
            timestamp=str(meta_raw.get("timestamp", "")),
            bars=int(meta_raw.get("bars", 0)),
        ),
        harmonics=_dict_to_harmonic_info(val.get("harmonics")),
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
async def run_symbol_analysis(symbol: str, session: SessionDep) -> AnalysisResponse:
    """Run on-demand analysis for a single ticker (inline, returns immediately)."""
    sym_result = await session.execute(
        select(Symbol).where(Symbol.ticker == symbol.upper())
    )
    sym = sym_result.scalar_one_or_none()
    if sym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Symbol {symbol} not found")

    result = await run_analysis_for_ticker(sym.id, sym.ticker, session)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient OHLCV data for {symbol}. Trigger a data refresh first.",
        )

    await session.commit()
    return _result_to_response(result)
