"""
Integration tests for all SQLAlchemy models against a real TimescaleDB container.

Covers:
- Basic CRUD for each of the 14 tables
- Hypertable behavior: OHLCV time-range query
- UNIQUE constraints raise IntegrityError
- Enum validation at the Python level
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    OHLCV,
    Divergence,
    IndicatorCache,
    IngestionLog,
    PatternDetection,
    SARating,
    ScanProfile,
    ScanResult,
    ScanRun,
    SignalResult,
    SwingPoint,
    Symbol,
    Watchlist,
    WatchlistItem,
)
from app.models.enums import (
    PatternType,
    SALetterGrade,
    ScanRunStatus,
    SignalCategory,
    SignalDirection,
    TimeframeEnum,
)
from tests.factories import (
    create_ohlcv_bars,
    create_sa_rating,
    create_scan_profile,
    create_scan_run,
    create_symbol,
    create_watchlist,
    create_watchlist_item,
)
from tests.generators import gen_uptrend

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# symbols
# ---------------------------------------------------------------------------


async def test_symbol_crud(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session, ticker="CRUD1", name="CRUD Test Co")
    assert symbol.id is not None

    fetched = await db_session.get(Symbol, symbol.id)
    assert fetched is not None
    assert fetched.ticker == "CRUD1"

    fetched.name = "Updated Name"
    await db_session.flush()
    refreshed = await db_session.get(Symbol, symbol.id)
    assert refreshed is not None
    assert refreshed.name == "Updated Name"

    await db_session.delete(fetched)
    await db_session.flush()
    deleted = await db_session.get(Symbol, symbol.id)
    assert deleted is None


async def test_symbol_unique_ticker_constraint(db_session: AsyncSession) -> None:
    ticker = f"DUP{uuid.uuid4().hex[:4].upper()}"
    await create_symbol(db_session, ticker=ticker)
    with pytest.raises(IntegrityError):
        await create_symbol(db_session, ticker=ticker)


# ---------------------------------------------------------------------------
# watchlists / watchlist_items
# ---------------------------------------------------------------------------


async def test_watchlist_crud(db_session: AsyncSession) -> None:
    wl = await create_watchlist(db_session, name="My Test List")
    assert wl.id is not None

    fetched = await db_session.get(Watchlist, wl.id)
    assert fetched is not None
    assert fetched.name == "My Test List"


async def test_watchlist_item_links_symbol_and_list(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    watchlist = await create_watchlist(db_session)
    item = await create_watchlist_item(db_session, watchlist=watchlist, symbol=symbol)

    assert item.id is not None
    assert item.watchlist_id == watchlist.id
    assert item.symbol_id == symbol.id


async def test_watchlist_item_unique_constraint(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    watchlist = await create_watchlist(db_session)
    await create_watchlist_item(db_session, watchlist=watchlist, symbol=symbol)

    with pytest.raises(IntegrityError):
        await create_watchlist_item(db_session, watchlist=watchlist, symbol=symbol)


# ---------------------------------------------------------------------------
# sa_ratings
# ---------------------------------------------------------------------------


async def test_sa_rating_crud(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    rating = await create_sa_rating(
        db_session,
        symbol=symbol,
        snapshot_date=date(2024, 1, 15),
        quant_score=4.25,
        valuation_grade=SALetterGrade.B_PLUS,
    )
    assert rating.id is not None

    fetched = await db_session.get(SARating, rating.id)
    assert fetched is not None
    assert fetched.valuation_grade == SALetterGrade.B_PLUS


async def test_sa_rating_unique_symbol_date(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    snap = date(2024, 6, 1)
    await create_sa_rating(db_session, symbol=symbol, snapshot_date=snap)

    with pytest.raises(IntegrityError):
        await create_sa_rating(db_session, symbol=symbol, snapshot_date=snap)


# ---------------------------------------------------------------------------
# ohlcv (hypertable)
# ---------------------------------------------------------------------------


async def test_ohlcv_insert_and_time_range_query(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    df = gen_uptrend(bars=30, seed=42)
    count = await create_ohlcv_bars(db_session, symbol, df)
    assert count == 30

    # Query with time range
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    end = datetime(2024, 1, 12, tzinfo=timezone.utc)
    stmt = (
        select(OHLCV)
        .where(OHLCV.symbol_id == symbol.id)
        .where(OHLCV.time >= start)
        .where(OHLCV.time <= end)
        .where(OHLCV.timeframe == TimeframeEnum.D1)
    )
    result = await db_session.execute(stmt)
    bars = result.scalars().all()
    assert len(bars) > 0
    assert all(start <= b.time <= end for b in bars)


async def test_ohlcv_hypertable_exists(db_session: AsyncSession) -> None:
    """Verify the ohlcv table is registered as a TimescaleDB hypertable."""
    result = await db_session.execute(
        text(
            "SELECT count(*) FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'ohlcv'"
        )
    )
    count = result.scalar_one()
    assert count == 1, "ohlcv is not a TimescaleDB hypertable"


# ---------------------------------------------------------------------------
# indicator_cache (hypertable)
# ---------------------------------------------------------------------------


async def test_indicator_cache_crud(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    ts = datetime(2024, 3, 1, tzinfo=timezone.utc)
    cache = IndicatorCache(
        time=ts,
        symbol_id=symbol.id,
        timeframe=TimeframeEnum.D1,
        indicator_name="rsi",
        params_hash="abc123",
        value={"rsi": 45.5},
    )
    db_session.add(cache)
    await db_session.flush()

    stmt = select(IndicatorCache).where(
        IndicatorCache.symbol_id == symbol.id,
        IndicatorCache.indicator_name == "rsi",
    )
    result = await db_session.execute(stmt)
    fetched = result.scalar_one_or_none()
    assert fetched is not None
    assert fetched.value == {"rsi": 45.5}


# ---------------------------------------------------------------------------
# scan_profiles / scan_runs / scan_results / signal_results
# ---------------------------------------------------------------------------


async def test_scan_profile_crud(db_session: AsyncSession) -> None:
    profile = await create_scan_profile(db_session, name="Breakout Profile")
    assert profile.id is not None
    fetched = await db_session.get(ScanProfile, profile.id)
    assert fetched is not None
    assert fetched.name == "Breakout Profile"


async def test_scan_run_crud(db_session: AsyncSession) -> None:
    profile = await create_scan_profile(db_session)
    watchlist = await create_watchlist(db_session)
    run = await create_scan_run(db_session, profile=profile, watchlist=watchlist)
    assert run.id is not None
    assert run.status == ScanRunStatus.PENDING


async def test_scan_result_crud(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    profile = await create_scan_profile(db_session)
    watchlist = await create_watchlist(db_session)
    run = await create_scan_run(db_session, profile=profile, watchlist=watchlist)

    result = ScanResult(
        scan_run_id=run.id,
        symbol_id=symbol.id,
        composite_score=0.72,
        direction=SignalDirection.BULLISH,
        category_scores={"trend": 0.8, "momentum": 0.6},
        profile_matches=[],
        categories_agreeing=2,
        rank=1,
    )
    db_session.add(result)
    await db_session.flush()
    assert result.id is not None


async def test_signal_result_crud(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    profile = await create_scan_profile(db_session)
    watchlist = await create_watchlist(db_session)
    run = await create_scan_run(db_session, profile=profile, watchlist=watchlist)

    sig = SignalResult(
        scan_run_id=run.id,
        symbol_id=symbol.id,
        indicator_name="rsi_14",
        category=SignalCategory.MOMENTUM,
        signal_value=0.43,
        direction=SignalDirection.BULLISH,
        raw_values={"rsi": 28.5},
    )
    db_session.add(sig)
    await db_session.flush()
    assert sig.id is not None


# ---------------------------------------------------------------------------
# pattern_detections / divergences / swing_points
# ---------------------------------------------------------------------------


async def test_pattern_detection_crud(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    profile = await create_scan_profile(db_session)
    watchlist = await create_watchlist(db_session)
    run = await create_scan_run(db_session, profile=profile, watchlist=watchlist)

    now = datetime.now(tz=timezone.utc)
    pattern = PatternDetection(
        scan_run_id=run.id,
        symbol_id=symbol.id,
        timeframe=TimeframeEnum.D1,
        pattern_type=PatternType.HARMONIC,
        pattern_name="gartley",
        direction=SignalDirection.BULLISH,
        confidence=0.85,
        geometry={"x": 100.0, "a": 120.0},
        detected_at=now,
    )
    db_session.add(pattern)
    await db_session.flush()
    assert pattern.id is not None


async def test_divergence_crud(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    profile = await create_scan_profile(db_session)
    watchlist = await create_watchlist(db_session)
    run = await create_scan_run(db_session, profile=profile, watchlist=watchlist)

    now = datetime.now(tz=timezone.utc)
    div = Divergence(
        scan_run_id=run.id,
        symbol_id=symbol.id,
        timeframe=TimeframeEnum.D1,
        indicator_name="rsi",
        divergence_type="regular",
        direction=SignalDirection.BULLISH,
        pivots={"p1": {"time": "2024-01-10", "price": 100.0}},
        confidence=0.75,
        detected_at=now,
    )
    db_session.add(div)
    await db_session.flush()
    assert div.id is not None


async def test_swing_point_crud(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    now = datetime.now(tz=timezone.utc)

    sp = SwingPoint(
        symbol_id=symbol.id,
        timeframe=TimeframeEnum.D1,
        time=now,
        type="high",
        price=155.75,
        strength=5,
    )
    db_session.add(sp)
    await db_session.flush()
    assert sp.id is not None


# ---------------------------------------------------------------------------
# ingestion_log
# ---------------------------------------------------------------------------


async def test_ingestion_log_crud(db_session: AsyncSession) -> None:
    symbol = await create_symbol(db_session)
    log = IngestionLog(
        symbol_id=symbol.id,
        timeframe=TimeframeEnum.D1,
        source="yfinance",
        bars_fetched=100,
        status="success",
    )
    db_session.add(log)
    await db_session.flush()
    assert log.id is not None


# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------


async def test_invalid_sa_letter_grade_rejected(db_session: AsyncSession) -> None:
    """Invalid enum values should be rejected at the Python/SQLAlchemy level."""
    with pytest.raises((ValueError, KeyError)):
        SALetterGrade("INVALID_GRADE")
