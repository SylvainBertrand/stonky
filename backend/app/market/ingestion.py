"""Orchestrate broad market data fetching: yfinance + FRED + sentiment."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ingestion.fetcher import fetch_and_store
from app.market.fred_client import FRED_SERIES, fetch_fred_series
from app.market.sentiment import scrape_aaii, scrape_naaim
from app.models import MacroSeries, SentimentData, Symbol
from app.models.enums import TimeframeEnum
from app.models.watchlists import Watchlist, WatchlistItem

logger = logging.getLogger(__name__)

MARKET_TICKERS = [
    "^GSPC",
    "RSP",
    "QQQ",
    "^VIX",
    "DX-Y.NYB",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
]


async def ensure_market_symbols(session: AsyncSession) -> None:
    """Create market symbols and _market_indices watchlist if they don't exist."""
    for ticker in MARKET_TICKERS:
        existing = await session.execute(select(Symbol).where(Symbol.ticker == ticker))
        if existing.scalar_one_or_none() is None:
            session.add(Symbol(ticker=ticker, name=ticker, is_active=True))

    wl_result = await session.execute(select(Watchlist).where(Watchlist.name == "_market_indices"))
    wl = wl_result.scalar_one_or_none()
    if wl is None:
        wl = Watchlist(name="_market_indices")
        session.add(wl)
        await session.flush()

    for ticker in MARKET_TICKERS:
        sym_result = await session.execute(select(Symbol).where(Symbol.ticker == ticker))
        sym = sym_result.scalar_one_or_none()
        if sym:
            existing_item = await session.execute(
                select(WatchlistItem).where(
                    WatchlistItem.watchlist_id == wl.id,
                    WatchlistItem.symbol_id == sym.id,
                )
            )
            if existing_item.scalar_one_or_none() is None:
                session.add(WatchlistItem(watchlist_id=wl.id, symbol_id=sym.id))

    await session.commit()


async def fetch_market_ohlcv(session: AsyncSession) -> None:
    """Fetch OHLCV for all market tickers using existing fetcher.

    Uses incremental=False on first run (no existing bars) to backfill history,
    then incremental=True on subsequent runs.
    """
    from app.models.ohlcv import OHLCV

    # Check if we have any market data yet
    sample = await session.execute(
        select(OHLCV.time)
        .join(Symbol, OHLCV.symbol_id == Symbol.id)
        .where(Symbol.ticker == "^GSPC", OHLCV.timeframe == TimeframeEnum.D1)
        .limit(1)
    )
    has_data = sample.scalar_one_or_none() is not None

    result = await fetch_and_store(
        session, MARKET_TICKERS, timeframe=TimeframeEnum.D1, incremental=has_data
    )
    logger.info("Market OHLCV fetch: %s", result)


async def fetch_fred_data(session: AsyncSession) -> None:
    """Fetch all FRED series and store in macro_series table."""
    api_key = settings.fred_api_key
    if not api_key:
        logger.warning("FRED_API_KEY not set — skipping FRED data fetch")
        return

    start = (date.today() - timedelta(days=730)).isoformat()

    for series_id in FRED_SERIES:
        df = await fetch_fred_series(series_id, api_key, start)
        if df.empty:
            continue

        for _, row in df.iterrows():
            stmt = (
                pg_insert(MacroSeries.__table__)
                .values(
                    series_id=series_id,
                    date=row["date"],
                    value=row["value"],
                )
                .on_conflict_do_nothing(constraint="uq_macro_series_sid_date")
            )
            await session.execute(stmt)

        await session.commit()
        logger.info("FRED %s: stored %d observations", series_id, len(df))


async def fetch_sentiment_data(session: AsyncSession) -> None:
    """Scrape AAII/NAAIM and store in sentiment_data table."""
    aaii_readings = await scrape_aaii()
    for r in aaii_readings:
        stmt = (
            pg_insert(SentimentData.__table__)
            .values(
                source="aaii",
                week_ending=r.week_ending,
                value=r.bull_bear_spread,
                extra={
                    "bullish_pct": r.bullish_pct,
                    "neutral_pct": r.neutral_pct,
                    "bearish_pct": r.bearish_pct,
                },
            )
            .on_conflict_do_nothing(constraint="uq_sentiment_source_week")
        )
        await session.execute(stmt)

    naaim_readings = await scrape_naaim()
    for r in naaim_readings:
        stmt = (
            pg_insert(SentimentData.__table__)
            .values(
                source="naaim",
                week_ending=r["week_ending"],
                value=r["exposure"],
            )
            .on_conflict_do_nothing(constraint="uq_sentiment_source_week")
        )
        await session.execute(stmt)

    await session.commit()
    logger.info(
        "Sentiment: stored %d AAII + %d NAAIM readings",
        len(aaii_readings),
        len(naaim_readings),
    )


async def run_market_data_refresh() -> None:
    """Full market data refresh — called by scheduler or manual trigger."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        logger.info("Market data refresh: starting")
        await ensure_market_symbols(session)
        await fetch_market_ohlcv(session)
        await fetch_fred_data(session)
        await fetch_sentiment_data(session)
        logger.info("Market data refresh: complete")
