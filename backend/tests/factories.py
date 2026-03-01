"""
Factory functions for creating test DB objects with sensible defaults.

Each function:
- Accepts **overrides to customize any field
- Calls session.flush() (not commit) so the transaction can be rolled back
- Returns the created ORM object

Usage:
    symbol = await create_symbol(session, ticker="AAPL")
    watchlist = await create_watchlist(session, name="Tech Stocks")
    item = await create_watchlist_item(session, watchlist=watchlist, symbol=symbol)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    OHLCV,
    SARating,
    ScanProfile,
    ScanRun,
    Symbol,
    Watchlist,
    WatchlistItem,
)
from app.models.enums import ScanRunStatus, TimeframeEnum


def _unique_ticker() -> str:
    return f"TST{uuid.uuid4().hex[:6].upper()}"


async def create_symbol(session: AsyncSession, **overrides: Any) -> Symbol:
    defaults: dict[str, Any] = {
        "ticker": _unique_ticker(),
        "name": "Test Company Inc.",
        "exchange": "NASDAQ",
        "asset_type": "stock",
        "sector": "Technology",
        "industry": "Software",
        "is_active": True,
    }
    defaults.update(overrides)
    symbol = Symbol(**defaults)
    session.add(symbol)
    await session.flush()
    return symbol


async def create_watchlist(session: AsyncSession, **overrides: Any) -> Watchlist:
    defaults: dict[str, Any] = {
        "name": f"Test Watchlist {uuid.uuid4().hex[:8]}",
        "description": "Auto-generated test watchlist",
        "is_default": False,
    }
    defaults.update(overrides)
    watchlist = Watchlist(**defaults)
    session.add(watchlist)
    await session.flush()
    return watchlist


async def create_watchlist_item(
    session: AsyncSession,
    watchlist: Watchlist,
    symbol: Symbol,
    **overrides: Any,
) -> WatchlistItem:
    defaults: dict[str, Any] = {
        "watchlist_id": watchlist.id,
        "symbol_id": symbol.id,
        "notes": None,
    }
    defaults.update(overrides)
    item = WatchlistItem(**defaults)
    session.add(item)
    await session.flush()
    return item


async def create_scan_profile(session: AsyncSession, **overrides: Any) -> ScanProfile:
    defaults: dict[str, Any] = {
        "name": f"Test Profile {uuid.uuid4().hex[:8]}",
        "description": "Auto-generated test scan profile",
        "indicators": [],
        "category_weights": {
            "trend": 0.30,
            "momentum": 0.20,
            "volume": 0.15,
            "volatility": 0.10,
            "support_resistance": 0.10,
            "divergence": 0.10,
            "pattern": 0.05,
        },
        "filters": {"min_composite_score": 0.3},
        "timeframes": {"primary": "1d"},
        "is_active": True,
    }
    defaults.update(overrides)
    profile = ScanProfile(**defaults)
    session.add(profile)
    await session.flush()
    return profile


async def create_scan_run(
    session: AsyncSession,
    profile: ScanProfile,
    watchlist: Watchlist,
    **overrides: Any,
) -> ScanRun:
    defaults: dict[str, Any] = {
        "profile_id": profile.id,
        "watchlist_id": watchlist.id,
        "status": ScanRunStatus.PENDING,
    }
    defaults.update(overrides)
    run = ScanRun(**defaults)
    session.add(run)
    await session.flush()
    return run


async def create_ohlcv_bars(
    session: AsyncSession,
    symbol: Symbol,
    bars_df: pd.DataFrame,
    timeframe: str = "1d",
) -> int:
    """
    Bulk-insert OHLCV bars from a DataFrame.

    The DataFrame must have columns: time, open, high, low, close, volume.
    Returns the number of rows inserted.
    """
    tf_enum = TimeframeEnum(timeframe)
    rows: list[OHLCV] = []
    for _, row in bars_df.iterrows():
        bar_time = row["time"]
        if isinstance(bar_time, str):
            bar_time = datetime.fromisoformat(bar_time).replace(tzinfo=timezone.utc)
        elif hasattr(bar_time, "to_pydatetime"):
            bar_time = bar_time.to_pydatetime().replace(tzinfo=timezone.utc)

        rows.append(
            OHLCV(
                time=bar_time,
                symbol_id=symbol.id,
                timeframe=tf_enum,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=int(row["volume"]),
            )
        )
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def create_sa_rating(
    session: AsyncSession,
    symbol: Symbol,
    **overrides: Any,
) -> SARating:
    defaults: dict[str, Any] = {
        "symbol_id": symbol.id,
        "snapshot_date": date.today(),
        "quant_score": 3.75,
        "sa_analyst_score": 4.00,
        "wall_st_score": 3.50,
    }
    defaults.update(overrides)
    rating = SARating(**defaults)
    session.add(rating)
    await session.flush()
    return rating
