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
from app.ingestion.sa_import import import_sa_ratings
from app.models.enums import TimeframeEnum
from app.models.ingestion_log import IngestionLog
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem
from app.schemas.watchlist import (
    IngestionStatusEntry,
    SymbolAdd,
    WatchlistCreate,
    WatchlistDetail,
    WatchlistItemRead,
    WatchlistRead,
)

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_watchlist_or_404(session: AsyncSession, watchlist_id: int) -> Watchlist:
    result = await session.execute(
        select(Watchlist).where(Watchlist.id == watchlist_id)
    )
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
        existing = await session.execute(
            select(Watchlist).where(Watchlist.is_default.is_(True))
        )
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


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(watchlist_id: int, session: SessionDep) -> None:
    wl = await _get_watchlist_or_404(session, watchlist_id)
    await session.delete(wl)
    await session.commit()


# ---------------------------------------------------------------------------
# Symbol management
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
    sym_result = await session.execute(
        select(Symbol).where(Symbol.ticker == body.ticker)
    )
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

    sym_result = await session.execute(
        select(Symbol.id).where(Symbol.ticker == ticker.upper())
    )
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
    from sqlalchemy import desc, over
    from sqlalchemy.sql.functions import rank as rank_fn

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
