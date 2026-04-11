"""
Stocks API — per-symbol OHLCV data with chart overlays.

Endpoints:
  GET /api/stocks/{symbol}/ohlcv       → candlestick bars + EMA/Supertrend overlays
                                         (1min/5min/15min/30min via yfinance,
                                          1h/4h/1d/1w/1mo from the DB hypertable)
  GET /api/stocks/{symbol}/price       → real-time last price + day change
  GET /api/stocks/{symbol}/indicators  → latest-bar raw indicator values
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Annotated, Any

import pandas as pd
import pandas_ta as ta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.indicators.trend import compute_ema
from app.analysis.pipeline import (
    aggregate_daily_to_monthly,
    aggregate_daily_to_weekly,
    aggregate_hourly_to_4h,
)
from app.db.session import get_session
from app.models.enums import TimeframeEnum
from app.models.ohlcv import OHLCV
from app.models.symbols import Symbol
from app.schemas.indicators import IndicatorValuesResponse
from app.schemas.stocks import StockPriceResponse
from app.services import price_service
from app.services.indicators_service import (
    MIN_BARS_FOR_EMA200,
    compute_latest_indicators,
)
from app.services.intraday_fetcher import (
    IntradayUnavailableError,
    fetch_intraday_ohlcv,
    is_intraday_timeframe,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/stocks", tags=["stocks"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_TIMEFRAME_MAP: dict[str, TimeframeEnum] = {
    "1min": TimeframeEnum.M1,
    "5min": TimeframeEnum.M5,
    "15min": TimeframeEnum.M15,
    "30min": TimeframeEnum.M30,
    "1h": TimeframeEnum.H1,
    "4h": TimeframeEnum.H4,
    "1d": TimeframeEnum.D1,
    "1w": TimeframeEnum.W1,
    "1mo": TimeframeEnum.MO1,
}


def _rows_to_df(rows: list[Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "time": row.time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": int(row.volume),
            }
            for row in rows
        ]
    )


def _is_intraday(tf: TimeframeEnum) -> bool:
    return tf in (
        TimeframeEnum.M1,
        TimeframeEnum.M5,
        TimeframeEnum.M15,
        TimeframeEnum.M30,
        TimeframeEnum.H1,
        TimeframeEnum.H4,
    )


def _format_time(t: Any, intraday: bool) -> int | str:
    """Return Unix timestamp (int) for intraday, 'YYYY-MM-DD' string otherwise."""
    if intraday:
        return int(pd.Timestamp(t).timestamp())
    return pd.Timestamp(t).strftime("%Y-%m-%d")


@router.get("/{symbol}/ohlcv", response_model=dict[str, Any])
async def get_ohlcv(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[
        str,
        Query(
            description=(
                "Timeframe: 1min, 5min, 15min, 30min (yfinance on-demand), "
                "1h, 4h, 1d, 1w, or 1mo (DB-backed)"
            )
        ),
    ] = "1d",
    bars: Annotated[int, Query(ge=20, le=500)] = 200,
    before: Annotated[
        str | None,
        Query(
            description=(
                "ISO date — return bars before this date. "
                "Ignored for intraday timeframes (yfinance returns the most "
                "recent rolling window only)."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """
    Return raw OHLCV bars plus pre-computed chart overlays for a symbol.

    Overlays:
    - ema_21, ema_50, ema_200  — line values
    - supertrend               — value + direction (1=bullish, -1=bearish)
    """
    sym_result = await session.execute(select(Symbol).where(Symbol.ticker == symbol.upper()))
    sym = sym_result.scalar_one_or_none()
    if sym is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Symbol {symbol} not found"
        )

    tf = _TIMEFRAME_MAP.get(timeframe, TimeframeEnum.D1)
    has_more = False

    # ── Intraday (1/5/15/30 min) — fetch from yfinance on demand ────────
    # Sub-daily bars are not persisted to the OHLCV hypertable yet (a
    # scheduled intraday fetcher is a follow-on task), so STONKY-003
    # serves these timeframes via direct yfinance lookup. The `before`
    # cursor is ignored: yfinance returns the most recent rolling window
    # only, and there is no historical depth to page back through.
    if is_intraday_timeframe(timeframe):
        try:
            df = await fetch_intraday_ohlcv(symbol, timeframe, bars)
        except IntradayUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        if df.empty:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No intraday OHLCV data for {symbol} at {timeframe}",
            )
        log.info("%s: fetched %d %s bars from yfinance", symbol, len(df), timeframe)

    # ── Timeframes that need aggregation from a base timeframe ──────────
    elif tf == TimeframeEnum.MO1:
        # Aggregate daily → monthly
        daily_query = select(OHLCV).where(
            OHLCV.symbol_id == sym.id, OHLCV.timeframe == TimeframeEnum.D1
        )
        daily_query = daily_query.order_by(desc(OHLCV.time)).limit(bars * 22)
        daily_result = await session.execute(daily_query)
        daily_rows = list(reversed(daily_result.scalars().all()))
        if not daily_rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No OHLCV data for {symbol}. Trigger a data refresh first.",
            )
        df = aggregate_daily_to_monthly(_rows_to_df(daily_rows))
        if before:
            before_dt = pd.Timestamp(datetime.fromisoformat(before), tz="UTC")
            df = df[pd.to_datetime(df["time"]) < before_dt].reset_index(drop=True)
        if len(df) > bars:
            has_more = True
            df = df.tail(bars).reset_index(drop=True)
        elif len(df) == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No OHLCV data for {symbol}. Trigger a data refresh first.",
            )
        log.info("%s: aggregated daily → %d monthly bars for chart", symbol, len(df))

    elif tf == TimeframeEnum.H4:
        # Try native 4H first, fallback to aggregate 1H → 4H
        query = select(OHLCV).where(OHLCV.symbol_id == sym.id, OHLCV.timeframe == TimeframeEnum.H4)
        if before:
            before_dt = datetime.fromisoformat(before)
            query = query.where(OHLCV.time < before_dt)
        query = query.order_by(desc(OHLCV.time)).limit(bars + 1)
        result = await session.execute(query)
        rows = list(reversed(result.scalars().all()))

        if rows:
            has_more = len(rows) > bars
            if has_more:
                rows = rows[1:]  # drop oldest extra row
            df = _rows_to_df(rows)
        else:
            # Fallback: aggregate 1H → 4H
            h1_query = select(OHLCV).where(
                OHLCV.symbol_id == sym.id, OHLCV.timeframe == TimeframeEnum.H1
            )
            h1_query = h1_query.order_by(desc(OHLCV.time)).limit(bars * 4)
            h1_result = await session.execute(h1_query)
            h1_rows = list(reversed(h1_result.scalars().all()))
            if not h1_rows:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No OHLCV data for {symbol}. Trigger a data refresh first.",
                )
            df = aggregate_hourly_to_4h(_rows_to_df(h1_rows))
            if before:
                before_dt = pd.Timestamp(datetime.fromisoformat(before), tz="UTC")
                df = df[pd.to_datetime(df["time"]) < before_dt].reset_index(drop=True)
            if len(df) > bars:
                has_more = True
                df = df.tail(bars).reset_index(drop=True)
            log.info("%s: aggregated 1H → %d 4H bars for chart", symbol, len(df))

    elif tf == TimeframeEnum.W1:
        # Try native weekly first, fallback to aggregate daily → weekly
        query = select(OHLCV).where(OHLCV.symbol_id == sym.id, OHLCV.timeframe == tf)
        if before:
            before_dt = datetime.fromisoformat(before)
            query = query.where(OHLCV.time < before_dt)
        query = query.order_by(desc(OHLCV.time)).limit(bars + 1)
        result = await session.execute(query)
        rows = list(reversed(result.scalars().all()))

        if rows:
            has_more = len(rows) > bars
            if has_more:
                rows = rows[1:]
            df = _rows_to_df(rows)
        else:
            # Fallback: aggregate daily → weekly
            daily_result = await session.execute(
                select(OHLCV)
                .where(OHLCV.symbol_id == sym.id, OHLCV.timeframe == TimeframeEnum.D1)
                .order_by(desc(OHLCV.time))
                .limit(bars * 5)
            )
            daily_rows = list(reversed(daily_result.scalars().all()))
            if not daily_rows:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No OHLCV data for {symbol}. Trigger a data refresh first.",
                )
            df = aggregate_daily_to_weekly(_rows_to_df(daily_rows))
            if before:
                before_dt = pd.Timestamp(datetime.fromisoformat(before), tz="UTC")
                df = df[pd.to_datetime(df["time"]) < before_dt].reset_index(drop=True)
            if len(df) > bars:
                has_more = True
                df = df.tail(bars).reset_index(drop=True)
            log.info(
                "%s: aggregated %d daily → %d weekly bars for chart",
                symbol,
                len(daily_rows),
                len(df),
            )

    else:
        # Direct DB query (1d, 1h)
        query = select(OHLCV).where(OHLCV.symbol_id == sym.id, OHLCV.timeframe == tf)
        if before:
            before_dt = datetime.fromisoformat(before)
            query = query.where(OHLCV.time < before_dt)
        query = query.order_by(desc(OHLCV.time)).limit(bars + 1)  # +1 for has_more
        result = await session.execute(query)
        rows = list(reversed(result.scalars().all()))

        has_more = len(rows) > bars
        if has_more:
            rows = rows[1:]  # drop oldest extra row

        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No OHLCV data for {symbol}. Trigger a data refresh first.",
            )
        df = _rows_to_df(rows)

    if df.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No OHLCV data for {symbol}. Trigger a data refresh first.",
        )

    # ── Format time values ──────────────────────────────────────────────
    intraday = _is_intraday(tf)
    times = pd.to_datetime(df["time"])
    time_values = [_format_time(t, intraday) for t in times]
    n = len(df)

    out_bars = [
        {
            "time": time_values[i],
            "open": float(df["open"].iloc[i]),
            "high": float(df["high"].iloc[i]),
            "low": float(df["low"].iloc[i]),
            "close": float(df["close"].iloc[i]),
            "volume": int(df["volume"].iloc[i]),
        }
        for i in range(n)
    ]

    # EMA overlays
    ema_df = compute_ema(df)

    def _ema_overlay(col: str) -> list[dict[str, Any]]:
        return [
            {"time": time_values[i], "value": round(float(ema_df[col].iloc[i]), 4)}
            for i in range(n)
            if pd.notna(ema_df[col].iloc[i])
        ]

    # Supertrend overlay
    supertrend_out: list[dict[str, Any]] = []
    try:
        st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
        if st is not None and not st.empty:
            val_col = next(
                (
                    c
                    for c in st.columns
                    if c.startswith("SUPERT_")
                    and not any(c.startswith(p) for p in ("SUPERTd_", "SUPERTl_", "SUPERTu_"))
                ),
                None,
            )
            dir_col = next((c for c in st.columns if c.startswith("SUPERTd_")), None)
            if val_col and dir_col:
                for i in range(n):
                    val = st[val_col].iloc[i]
                    direction = st[dir_col].iloc[i]
                    if pd.notna(val) and pd.notna(direction):
                        supertrend_out.append(
                            {
                                "time": time_values[i],
                                "value": round(float(val), 4),
                                "direction": int(direction),
                            }
                        )
    except Exception as exc:
        log.warning("Supertrend computation failed for %s: %s", symbol, exc)

    return {
        "symbol": symbol.upper(),
        "bars": out_bars,
        "has_more": has_more,
        "overlays": {
            "ema_21": _ema_overlay("ema_21"),
            "ema_50": _ema_overlay("ema_50"),
            "ema_200": _ema_overlay("ema_200"),
            "supertrend": supertrend_out,
        },
    }


@router.get("/{symbol}/price", response_model=StockPriceResponse)
async def get_current_price(symbol: str) -> StockPriceResponse:
    """
    Return the real-time last price and day-change for a symbol.

    Backed by `yfinance.Ticker.fast_info` with a process-local TTL cache
    (configurable via `settings.price_cache_ttl_seconds`, default 60s).
    Returns 404 if yfinance has no quote data for the symbol.
    """
    try:
        quote = await price_service.get_current_price(symbol)
    except price_service.TickerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return StockPriceResponse(
        symbol=quote.symbol,
        price=quote.price,
        change_abs=quote.change_abs,
        change_pct=quote.change_pct,
        timestamp=quote.timestamp,
    )


@router.get("/{symbol}/indicators", response_model=IndicatorValuesResponse)
async def get_indicators(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="Timeframe: 1h, 4h, 1d, 1w, or 1mo")] = "1d",
) -> IndicatorValuesResponse:
    """
    Return the latest-bar raw indicator values for a symbol/timeframe.

    Re-uses the existing computation pipeline in `app.analysis.indicators.*`
    and pulls the most recent value from each output column. Computation
    runs in a thread pool so the FastAPI event loop is never blocked.

    Returns 422 for unsupported timeframes and 404 if the symbol does not
    exist or has no OHLCV data at the requested timeframe.
    """
    if timeframe not in _TIMEFRAME_MAP:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"Unsupported timeframe '{timeframe}'. Use one of: {sorted(_TIMEFRAME_MAP)}"),
        )

    sym_result = await session.execute(select(Symbol).where(Symbol.ticker == symbol.upper()))
    sym = sym_result.scalar_one_or_none()
    if sym is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol {symbol} not found",
        )

    tf = _TIMEFRAME_MAP[timeframe]
    # Fetch enough bars to populate EMA-200 (oldest indicator window).
    fetch_limit = max(MIN_BARS_FOR_EMA200 + 50, 250)
    result = await session.execute(
        select(OHLCV)
        .where(OHLCV.symbol_id == sym.id, OHLCV.timeframe == tf)
        .order_by(desc(OHLCV.time))
        .limit(fetch_limit)
    )
    rows = list(reversed(result.scalars().all()))
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No OHLCV data for {symbol} at {timeframe}",
        )

    df = _rows_to_df(rows)

    # Run the (sync, CPU-bound) indicator pipeline off the event loop.
    loop = asyncio.get_running_loop()
    indicators = await loop.run_in_executor(None, compute_latest_indicators, df)

    latest_time = pd.Timestamp(rows[-1].time).isoformat()

    return IndicatorValuesResponse(
        symbol=symbol.upper(),
        timeframe=timeframe,
        timestamp=latest_time,
        indicators=indicators,
    )
