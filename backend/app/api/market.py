"""Market data API router — regime, breadth, momentum, macro, sentiment."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.market.calendar_service import get_market_status
from app.market.ingestion import run_market_data_refresh
from app.market.sentiment import parse_aaii_csv, parse_naaim_csv
from app.models import MacroSeries, MarketRegimeModel, SentimentData, Symbol
from app.models.enums import TimeframeEnum
from app.models.ohlcv import OHLCV
from app.schemas.market import (
    MarketRegimeResponse,
    MarketStatusResponse,
    RefreshStatusResponse,
    SentimentImportResponse,
    TimeSeriesItem,
    TimeSeriesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _get_ohlcv_close(
    session: AsyncSession, ticker: str, limit: int = 252
) -> list[dict[str, Any]]:
    sym_result = await session.execute(select(Symbol).where(Symbol.ticker == ticker))
    sym = sym_result.scalar_one_or_none()
    if not sym:
        return []
    result = await session.execute(
        select(OHLCV)
        .where(OHLCV.symbol_id == sym.id, OHLCV.timeframe == TimeframeEnum.D1)
        .order_by(desc(OHLCV.time))
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    return [{"date": r.time.isoformat()[:10], "close": float(r.close)} for r in rows]


@router.get("/regime", response_model=MarketRegimeResponse)
async def get_regime(session: SessionDep) -> MarketRegimeResponse:
    """Return the latest market regime classification."""
    result = await session.execute(
        select(MarketRegimeModel).order_by(desc(MarketRegimeModel.as_of_date)).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return MarketRegimeResponse(
            regime="unknown",
            breadth="unknown",
            momentum="unknown",
            sentiment="unknown",
            macro="unknown",
            summary="No market regime data available yet.",
            scanner_implication="Run a market data refresh to generate regime classification.",
        )
    return MarketRegimeResponse(
        as_of_date=row.as_of_date.isoformat(),
        regime=row.regime,
        breadth=row.breadth,
        momentum=row.momentum,
        sentiment=row.sentiment,
        macro=row.macro,
        summary=row.summary,
        scanner_implication=row.scanner_implication,
    )


@router.get("/breadth", response_model=TimeSeriesResponse)
async def get_breadth(session: SessionDep) -> TimeSeriesResponse:
    """Return SPX/RSP ratio time series for breadth analysis."""
    spx = await _get_ohlcv_close(session, "^GSPC")
    rsp = await _get_ohlcv_close(session, "RSP")

    if not spx or not rsp:
        return TimeSeriesResponse(labels=[], series=[])

    # Align by date and compute ratio
    spx_map = {d["date"]: d["close"] for d in spx}
    rsp_map = {d["date"]: d["close"] for d in rsp}
    common_dates = sorted(set(spx_map) & set(rsp_map))

    ratio = [round(spx_map[d] / rsp_map[d], 4) if rsp_map[d] else None for d in common_dates]

    return TimeSeriesResponse(
        labels=common_dates,
        series=[
            TimeSeriesItem(name="spx_rsp_ratio", data=ratio),
        ],
    )


@router.get("/momentum", response_model=TimeSeriesResponse)
async def get_momentum(session: SessionDep) -> TimeSeriesResponse:
    """Return SPX, QQQ, VIX close time series."""
    spx = await _get_ohlcv_close(session, "^GSPC")
    qqq = await _get_ohlcv_close(session, "QQQ")
    vix = await _get_ohlcv_close(session, "^VIX")

    labels = [d["date"] for d in spx]
    qqq_map = {d["date"]: d["close"] for d in qqq}
    vix_map = {d["date"]: d["close"] for d in vix}

    return TimeSeriesResponse(
        labels=labels,
        series=[
            TimeSeriesItem(name="SPX", data=[d["close"] for d in spx]),
            TimeSeriesItem(name="QQQ", data=[qqq_map.get(lbl) for lbl in labels]),
            TimeSeriesItem(name="VIX", data=[vix_map.get(lbl) for lbl in labels]),
        ],
    )


@router.get("/macro", response_model=TimeSeriesResponse)
async def get_macro(session: SessionDep) -> TimeSeriesResponse:
    """Return FRED series (DGS10, DGS2, M2SL) + DXY close."""
    fred_ids = ["DGS10", "DGS2", "M2SL"]
    fred_data: dict[str, list[dict[str, Any]]] = {}

    for sid in fred_ids:
        result = await session.execute(
            select(MacroSeries)
            .where(MacroSeries.series_id == sid)
            .order_by(desc(MacroSeries.date))
            .limit(252)
        )
        rows = list(result.scalars().all())
        rows.reverse()
        fred_data[sid] = [
            {"date": r.date.isoformat(), "value": float(r.value) if r.value is not None else None}
            for r in rows
        ]

    dxy = await _get_ohlcv_close(session, "DX-Y.NYB")

    # Use DGS10 dates as labels if available, else DXY
    if fred_data.get("DGS10"):
        labels = [d["date"] for d in fred_data["DGS10"]]
    elif dxy:
        labels = [d["date"] for d in dxy]
    else:
        labels = []

    dxy_map = {d["date"]: d["close"] for d in dxy}

    series_list: list[TimeSeriesItem] = []
    for sid in fred_ids:
        data_map = {d["date"]: d["value"] for d in fred_data.get(sid, [])}
        series_list.append(TimeSeriesItem(name=sid, data=[data_map.get(lbl) for lbl in labels]))

    series_list.append(TimeSeriesItem(name="DXY", data=[dxy_map.get(lbl) for lbl in labels]))

    return TimeSeriesResponse(labels=labels, series=series_list)


@router.get("/sentiment", response_model=TimeSeriesResponse)
async def get_sentiment(session: SessionDep) -> TimeSeriesResponse:
    """Return AAII bull/bear/spread + NAAIM exposure time series."""
    aaii_result = await session.execute(
        select(SentimentData)
        .where(SentimentData.source == "aaii")
        .order_by(desc(SentimentData.week_ending))
        .limit(104)
    )
    aaii_rows = list(aaii_result.scalars().all())
    aaii_rows.reverse()

    naaim_result = await session.execute(
        select(SentimentData)
        .where(SentimentData.source == "naaim")
        .order_by(desc(SentimentData.week_ending))
        .limit(104)
    )
    naaim_rows = list(naaim_result.scalars().all())
    naaim_rows.reverse()

    # Combine all dates
    all_dates = sorted(
        {r.week_ending.isoformat() for r in aaii_rows}
        | {r.week_ending.isoformat() for r in naaim_rows}
    )
    if not all_dates:
        return TimeSeriesResponse(labels=[], series=[])

    # Build maps
    aaii_map: dict[str, dict[str, Any]] = {}
    for r in aaii_rows:
        d = r.week_ending.isoformat()
        extra = r.extra or {}
        aaii_map[d] = {
            "spread": float(r.value),
            "bullish": extra.get("bullish_pct"),
            "bearish": extra.get("bearish_pct"),
        }
    naaim_map = {r.week_ending.isoformat(): float(r.value) for r in naaim_rows}

    return TimeSeriesResponse(
        labels=all_dates,
        series=[
            TimeSeriesItem(
                name="AAII Bull",
                data=[aaii_map.get(d, {}).get("bullish") for d in all_dates],
            ),
            TimeSeriesItem(
                name="AAII Bear",
                data=[aaii_map.get(d, {}).get("bearish") for d in all_dates],
            ),
            TimeSeriesItem(
                name="AAII Spread",
                data=[aaii_map.get(d, {}).get("spread") for d in all_dates],
            ),
            TimeSeriesItem(
                name="NAAIM Exposure",
                data=[naaim_map.get(d) for d in all_dates],
            ),
        ],
    )


@router.post("/sentiment/import", response_model=SentimentImportResponse)
async def import_sentiment(
    session: SessionDep,
    file: UploadFile,
    source: str = Query(..., pattern="^(aaii|naaim)$"),
) -> SentimentImportResponse:
    """Import AAII or NAAIM sentiment data from CSV upload."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    content = (await file.read()).decode("utf-8")

    if source == "aaii":
        readings = parse_aaii_csv(content)
        for r in readings:
            stmt = (
                pg_insert(SentimentData)
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
        count = len(readings)
    else:
        readings_naaim = parse_naaim_csv(content)
        for naaim_row in readings_naaim:
            stmt = (
                pg_insert(SentimentData)
                .values(
                    source="naaim",
                    week_ending=naaim_row["week_ending"],
                    value=naaim_row["exposure"],
                )
                .on_conflict_do_nothing(constraint="uq_sentiment_source_week")
            )
            await session.execute(stmt)
        count = len(readings_naaim)

    await session.commit()
    return SentimentImportResponse(source=source, rows_imported=count)


@router.post("/refresh", response_model=RefreshStatusResponse)
async def trigger_refresh() -> RefreshStatusResponse:
    """Trigger a full market data refresh as a background task."""
    asyncio.create_task(run_market_data_refresh())
    return RefreshStatusResponse(status="started")


@router.get("/status", response_model=MarketStatusResponse)
async def get_status() -> MarketStatusResponse:
    """
    Return the current NYSE market session status.

    Pure computation — no DB, no external API calls. Backed by
    `pandas_market_calendars` for accurate NYSE holiday handling.

    Sessions (NYSE local time, ET):
        pre-market   04:00 – 09:29
        regular      09:30 – 15:59
        after-hours  16:00 – 19:59
        closed       20:00 – 03:59 + weekends + NYSE holidays
    """
    snapshot = get_market_status()
    return MarketStatusResponse(
        is_open=snapshot.is_open,
        session=snapshot.session,
        next_open=snapshot.next_open.isoformat(),
        next_close=snapshot.next_close.isoformat(),
        timezone=snapshot.timezone,
    )
