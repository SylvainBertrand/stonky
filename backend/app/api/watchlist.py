"""Watchlist CRUD API + SA ratings import endpoint."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal, get_session
from app.ingestion.fetcher import fetch_and_store
from app.ingestion.sa_import import import_sa_ratings, parse_sa_spreadsheet
from app.models.ingestion_log import IngestionLog
from app.models.sa_ratings import SARating
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem
from app.schemas.watchlist import (
    IngestionStatusEntry,
    SAImportResult,
    SetActiveRequest,
    SymbolAdd,
    WatchlistCreate,
    WatchlistDetail,
    WatchlistItemRead,
    WatchlistItemWithRatings,
    WatchlistRead,
    WatchlistUpdate,
)

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_watchlist_or_404(session: AsyncSession, watchlist_id: int) -> Watchlist:
    result = await session.execute(select(Watchlist).where(Watchlist.id == watchlist_id))
    wl = result.scalar_one_or_none()
    if wl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    return wl


def _item_count_subquery() -> Any:
    from sqlalchemy import func, select

    from app.models.watchlists import WatchlistItem

    return (
        select(func.count())
        .where(WatchlistItem.watchlist_id == Watchlist.id)
        .correlate(Watchlist)
        .scalar_subquery()
    )


async def _watchlist_to_read(session: AsyncSession, wl: Watchlist) -> WatchlistRead:
    count_result = await session.execute(
        select(func.count(WatchlistItem.id)).where(WatchlistItem.watchlist_id == wl.id)
    )
    count = count_result.scalar_one()
    return WatchlistRead(
        id=wl.id,
        name=wl.name,
        description=wl.description,
        is_default=wl.is_default,
        created_at=wl.created_at,
        item_count=count,
    )


async def _watchlist_to_detail(session: AsyncSession, wl: Watchlist) -> WatchlistDetail:
    # Load items with their symbols
    result = await session.execute(
        select(WatchlistItem)
        .where(WatchlistItem.watchlist_id == wl.id)
        .options(selectinload(WatchlistItem.symbol))
        .order_by(WatchlistItem.added_at)
    )
    items = result.scalars().all()

    item_reads = [
        WatchlistItemRead(
            id=item.id,
            symbol_id=item.symbol_id,
            ticker=item.symbol.ticker,
            name=item.symbol.name,
            notes=item.notes,
            added_at=item.added_at,
        )
        for item in items
    ]

    return WatchlistDetail(
        id=wl.id,
        name=wl.name,
        description=wl.description,
        is_default=wl.is_default,
        created_at=wl.created_at,
        item_count=len(item_reads),
        items=item_reads,
    )


# ---------------------------------------------------------------------------
# Active watchlist endpoints — defined BEFORE /{watchlist_id} to avoid conflict
# ---------------------------------------------------------------------------


@router.get("/active", response_model=WatchlistRead)
async def get_active_watchlist(session: SessionDep) -> WatchlistRead:
    """Return the active (default) watchlist, or 404 if none is set."""
    result = await session.execute(select(Watchlist).where(Watchlist.is_default.is_(True)))
    wl = result.scalar_one_or_none()
    if wl is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active watchlist set",
        )
    return await _watchlist_to_read(session, wl)


@router.put("/active", response_model=WatchlistRead)
async def set_active_watchlist(body: SetActiveRequest, session: SessionDep) -> WatchlistRead:
    """Set the active (default) watchlist. Clears is_default on all others."""
    wl = await _get_watchlist_or_404(session, body.watchlist_id)

    # Clear all existing defaults
    existing = await session.execute(select(Watchlist).where(Watchlist.is_default.is_(True)))
    for existing_wl in existing.scalars().all():
        existing_wl.is_default = False

    wl.is_default = True
    await session.commit()
    await session.refresh(wl)
    return await _watchlist_to_read(session, wl)


# ---------------------------------------------------------------------------
# SA Ratings import — defined BEFORE /{watchlist_id} routes to avoid conflict
# ---------------------------------------------------------------------------


@router.post("/sa-ratings/import")
async def import_sa_ratings_file(
    file: UploadFile,
    session: SessionDep,
) -> dict[str, Any]:
    """Import SA ratings from an uploaded CSV or XLSX spreadsheet."""
    suffix = Path(file.filename or "upload").suffix.lower() or ".csv"
    allowed = {".csv", ".xlsx", ".xls"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{suffix}'. Use CSV or XLSX.",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    results = await import_sa_ratings(tmp_path, session)
    await session.commit()
    Path(tmp_path).unlink(missing_ok=True)

    return results


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[WatchlistRead])
async def list_watchlists(session: SessionDep) -> list[WatchlistRead]:
    result = await session.execute(select(Watchlist).order_by(Watchlist.name))
    watchlists = result.scalars().all()
    return [await _watchlist_to_read(session, wl) for wl in watchlists]


@router.post("", response_model=WatchlistDetail, status_code=status.HTTP_201_CREATED)
async def create_watchlist(body: WatchlistCreate, session: SessionDep) -> WatchlistDetail:
    # Enforce single default watchlist
    if body.is_default:
        existing = await session.execute(select(Watchlist).where(Watchlist.is_default.is_(True)))
        for wl in existing.scalars().all():
            wl.is_default = False

    wl = Watchlist(
        name=body.name,
        description=body.description,
        is_default=body.is_default,
    )
    session.add(wl)
    await session.flush()
    await session.commit()
    await session.refresh(wl)
    return await _watchlist_to_detail(session, wl)


@router.get("/{watchlist_id}", response_model=WatchlistDetail)
async def get_watchlist(watchlist_id: int, session: SessionDep) -> WatchlistDetail:
    wl = await _get_watchlist_or_404(session, watchlist_id)
    return await _watchlist_to_detail(session, wl)


@router.put("/{watchlist_id}", response_model=WatchlistRead)
async def rename_watchlist(
    watchlist_id: int,
    body: WatchlistUpdate,
    session: SessionDep,
) -> WatchlistRead:
    """Rename a watchlist."""
    wl = await _get_watchlist_or_404(session, watchlist_id)
    wl.name = body.name
    await session.commit()
    await session.refresh(wl)
    return await _watchlist_to_read(session, wl)


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(watchlist_id: int, session: SessionDep) -> None:
    wl = await _get_watchlist_or_404(session, watchlist_id)

    # If deleting the active watchlist, auto-activate another one
    if wl.is_default:
        other_result = await session.execute(
            select(Watchlist).where(Watchlist.id != watchlist_id).limit(1)
        )
        other = other_result.scalar_one_or_none()
        if other is not None:
            other.is_default = True

    await session.delete(wl)
    await session.commit()


# ---------------------------------------------------------------------------
# Items endpoints (with SA ratings)
# ---------------------------------------------------------------------------


@router.get(
    "/{watchlist_id}/items",
    response_model=list[WatchlistItemWithRatings],
)
async def get_watchlist_items(
    watchlist_id: int,
    session: SessionDep,
) -> list[WatchlistItemWithRatings]:
    """Return watchlist items joined with the latest SA rating per symbol."""
    await _get_watchlist_or_404(session, watchlist_id)

    # Subquery: latest snapshot_date per symbol
    latest_subq = (
        select(SARating.symbol_id, func.max(SARating.snapshot_date).label("max_date"))
        .group_by(SARating.symbol_id)
        .subquery()
    )

    rows = await session.execute(
        select(WatchlistItem, Symbol, SARating)
        .join(Symbol, Symbol.id == WatchlistItem.symbol_id)
        .outerjoin(latest_subq, latest_subq.c.symbol_id == Symbol.id)
        .outerjoin(
            SARating,
            (SARating.symbol_id == Symbol.id) & (SARating.snapshot_date == latest_subq.c.max_date),
        )
        .where(WatchlistItem.watchlist_id == watchlist_id)
        .order_by(WatchlistItem.added_at)
    )

    results: list[WatchlistItemWithRatings] = []
    for item, symbol, rating in rows:
        results.append(
            WatchlistItemWithRatings(
                id=item.id,
                symbol_id=item.symbol_id,
                ticker=symbol.ticker,
                name=symbol.name,
                notes=item.notes,
                added_at=item.added_at,
                quant_score=float(rating.quant_score)
                if rating and rating.quant_score is not None
                else None,
                momentum_grade=rating.momentum_grade.value
                if rating and rating.momentum_grade
                else None,
                valuation_grade=rating.valuation_grade.value
                if rating and rating.valuation_grade
                else None,
                growth_grade=rating.growth_grade.value if rating and rating.growth_grade else None,
            )
        )
    return results


@router.post(
    "/{watchlist_id}/items",
    response_model=WatchlistItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    watchlist_id: int,
    body: SymbolAdd,
    session: SessionDep,
) -> WatchlistItemRead:
    """Add a symbol to a watchlist by ticker."""
    await _get_watchlist_or_404(session, watchlist_id)

    # Resolve or auto-create symbol
    sym_result = await session.execute(select(Symbol).where(Symbol.ticker == body.ticker))
    symbol = sym_result.scalar_one_or_none()
    if symbol is None:
        symbol = Symbol(ticker=body.ticker, asset_type="stock")
        session.add(symbol)
        await session.flush()

    # Check for duplicate
    dup = await session.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist_id,
            WatchlistItem.symbol_id == symbol.id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{body.ticker} is already in this watchlist",
        )

    item = WatchlistItem(
        watchlist_id=watchlist_id,
        symbol_id=symbol.id,
        notes=body.notes,
    )
    session.add(item)
    await session.flush()
    await session.commit()
    await session.refresh(item)

    return WatchlistItemRead(
        id=item.id,
        symbol_id=symbol.id,
        ticker=symbol.ticker,
        name=symbol.name,
        notes=item.notes,
        added_at=item.added_at,
    )


@router.delete(
    "/{watchlist_id}/items/{ticker}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_item(
    watchlist_id: int,
    ticker: str,
    session: SessionDep,
) -> None:
    """Remove a symbol from a watchlist by ticker."""
    await _get_watchlist_or_404(session, watchlist_id)

    sym_result = await session.execute(select(Symbol.id).where(Symbol.ticker == ticker.upper()))
    symbol_id = sym_result.scalar_one_or_none()
    if symbol_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")

    item_result = await session.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist_id,
            WatchlistItem.symbol_id == symbol_id,
        )
    )
    item = item_result.scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{ticker.upper()} not in watchlist",
        )

    await session.delete(item)
    await session.commit()


# ---------------------------------------------------------------------------
# Scoped SA import
# ---------------------------------------------------------------------------


async def _backfill_tickers_bg(tickers: list[str]) -> None:
    """Background task: full OHLCV backfill for newly added tickers."""
    async with AsyncSessionLocal() as session:
        await fetch_and_store(session, tickers, incremental=False)
        await session.commit()


@router.post("/{watchlist_id}/import-sa", response_model=SAImportResult)
async def import_sa_for_watchlist(
    watchlist_id: int,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> SAImportResult:
    """Import SA spreadsheet scoped to a watchlist.

    Adds tickers to the watchlist, imports SA ratings, then kicks off
    a background OHLCV backfill for newly added symbols.
    """
    await _get_watchlist_or_404(session, watchlist_id)

    suffix = Path(file.filename or "upload").suffix.lower() or ".csv"
    allowed = {".csv", ".xlsx", ".xls"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{suffix}'. Use CSV or XLSX.",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Parse tickers from spreadsheet
        df = parse_sa_spreadsheet(tmp_path)
        tickers = [str(t).strip().upper() for t in df["ticker"].tolist() if t]

        added = 0
        skipped = 0
        new_tickers: list[str] = []

        for ticker in tickers:
            # Resolve or auto-create symbol
            sym_result = await session.execute(select(Symbol).where(Symbol.ticker == ticker))
            symbol = sym_result.scalar_one_or_none()
            if symbol is None:
                symbol = Symbol(ticker=ticker, asset_type="stock")
                session.add(symbol)
                await session.flush()

            # Check for duplicate in this watchlist
            dup = await session.execute(
                select(WatchlistItem).where(
                    WatchlistItem.watchlist_id == watchlist_id,
                    WatchlistItem.symbol_id == symbol.id,
                )
            )
            if dup.scalar_one_or_none() is not None:
                skipped += 1
            else:
                item = WatchlistItem(
                    watchlist_id=watchlist_id,
                    symbol_id=symbol.id,
                )
                session.add(item)
                added += 1
                new_tickers.append(ticker)

        # Import SA ratings
        ratings_result = await import_sa_ratings(tmp_path, session)
        ratings_imported = ratings_result.get("imported", 0)
        errors = ratings_result.get("errors", 0)

        await session.commit()

        # Kick off OHLCV backfill for newly added tickers
        if new_tickers:
            background_tasks.add_task(_backfill_tickers_bg, new_tickers)

    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return SAImportResult(
        added=added,
        skipped=skipped,
        ratings_imported=ratings_imported,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Symbol management (legacy /symbols endpoints kept for backward compat)
# ---------------------------------------------------------------------------


@router.post(
    "/{watchlist_id}/symbols",
    response_model=WatchlistItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_symbol(
    watchlist_id: int,
    body: SymbolAdd,
    session: SessionDep,
) -> WatchlistItemRead:
    await _get_watchlist_or_404(session, watchlist_id)

    # Resolve or auto-create symbol
    sym_result = await session.execute(select(Symbol).where(Symbol.ticker == body.ticker))
    symbol = sym_result.scalar_one_or_none()
    if symbol is None:
        symbol = Symbol(ticker=body.ticker, asset_type="stock")
        session.add(symbol)
        await session.flush()

    # Check for duplicate
    dup = await session.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist_id,
            WatchlistItem.symbol_id == symbol.id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{body.ticker} is already in this watchlist",
        )

    item = WatchlistItem(
        watchlist_id=watchlist_id,
        symbol_id=symbol.id,
        notes=body.notes,
    )
    session.add(item)
    await session.flush()
    await session.commit()
    await session.refresh(item)

    return WatchlistItemRead(
        id=item.id,
        symbol_id=symbol.id,
        ticker=symbol.ticker,
        name=symbol.name,
        notes=item.notes,
        added_at=item.added_at,
    )


@router.delete(
    "/{watchlist_id}/symbols/{ticker}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_symbol(
    watchlist_id: int,
    ticker: str,
    session: SessionDep,
) -> None:
    await _get_watchlist_or_404(session, watchlist_id)

    sym_result = await session.execute(select(Symbol.id).where(Symbol.ticker == ticker.upper()))
    symbol_id = sym_result.scalar_one_or_none()
    if symbol_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")

    item_result = await session.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist_id,
            WatchlistItem.symbol_id == symbol_id,
        )
    )
    item = item_result.scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{ticker.upper()} not in watchlist",
        )

    await session.delete(item)
    await session.commit()


# ---------------------------------------------------------------------------
# Refresh & status
# ---------------------------------------------------------------------------


async def _refresh_watchlist_bg(watchlist_id: int) -> None:
    """Background task: fetch OHLCV for all symbols in a watchlist."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Symbol.ticker)
            .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
            .where(WatchlistItem.watchlist_id == watchlist_id, Symbol.is_active.is_(True))
        )
        tickers = list(result.scalars().all())
        if not tickers:
            return

        await fetch_and_store(session, tickers, incremental=True)
        await session.commit()


@router.post("/{watchlist_id}/refresh")
async def refresh_watchlist(
    watchlist_id: int,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> dict[str, Any]:
    """Trigger an incremental OHLCV refresh for all symbols in the watchlist."""
    wl = await _get_watchlist_or_404(session, watchlist_id)

    # Collect tickers for the immediate response
    result = await session.execute(
        select(Symbol.ticker)
        .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
        .where(WatchlistItem.watchlist_id == watchlist_id, Symbol.is_active.is_(True))
    )
    tickers = list(result.scalars().all())

    background_tasks.add_task(_refresh_watchlist_bg, watchlist_id)

    return {
        "status": "queued",
        "watchlist_id": wl.id,
        "watchlist_name": wl.name,
        "symbols": tickers,
    }


@router.get("/{watchlist_id}/status", response_model=list[IngestionStatusEntry])
async def watchlist_status(
    watchlist_id: int,
    session: SessionDep,
) -> list[IngestionStatusEntry]:
    """Return the most recent ingestion log entry per symbol in the watchlist."""
    await _get_watchlist_or_404(session, watchlist_id)

    # Latest log per symbol: subquery ranks by fetched_at desc
    from sqlalchemy import desc

    # Simpler approach: one query per symbol using LATERAL or just fetch all and deduplicate in Python
    syms_result = await session.execute(
        select(Symbol.id, Symbol.ticker)
        .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
        .where(WatchlistItem.watchlist_id == watchlist_id)
    )
    symbols = syms_result.all()

    entries: list[IngestionStatusEntry] = []
    for sym_id, ticker in symbols:
        log_result = await session.execute(
            select(IngestionLog)
            .where(IngestionLog.symbol_id == sym_id)
            .order_by(desc(IngestionLog.fetched_at))
            .limit(1)
        )
        log = log_result.scalar_one_or_none()
        if log is not None:
            entries.append(
                IngestionStatusEntry(
                    ticker=ticker,
                    timeframe=log.timeframe.value,
                    source=log.source,
                    bars_fetched=log.bars_fetched,
                    latest_bar=log.latest_bar,
                    status=log.status,
                    error_message=log.error_message,
                    fetched_at=log.fetched_at,
                )
            )

    return entries
