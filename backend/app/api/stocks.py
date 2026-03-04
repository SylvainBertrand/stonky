"""
Stocks API — per-symbol OHLCV data with chart overlays.

Endpoints:
  GET /api/stocks/{symbol}/ohlcv  → candlestick bars + EMA/Supertrend overlays
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

import pandas as pd
import pandas_ta as ta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.indicators.trend import compute_ema
from app.analysis.pipeline import aggregate_daily_to_weekly
from app.db.session import get_session
from app.models.enums import TimeframeEnum
from app.models.ohlcv import OHLCV
from app.models.symbols import Symbol

log = logging.getLogger(__name__)

router = APIRouter(prefix="/stocks", tags=["stocks"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_TIMEFRAME_MAP: dict[str, TimeframeEnum] = {
    "1d": TimeframeEnum.D1,
    "1w": TimeframeEnum.W1,
}


def _rows_to_df(rows: list[Any]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "time": row.time,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": int(row.volume),
        }
        for row in rows
    ])


@router.get("/{symbol}/ohlcv", response_model=dict[str, Any])
async def get_ohlcv(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="Timeframe: 1d or 1w")] = "1d",
    bars: Annotated[int, Query(ge=20, le=500)] = 200,
) -> dict[str, Any]:
    """
    Return raw OHLCV bars plus pre-computed chart overlays for a symbol.

    Overlays:
    - ema_21, ema_50, ema_200  — line values
    - supertrend               — value + direction (1=bullish, -1=bearish)
    """
    sym_result = await session.execute(
        select(Symbol).where(Symbol.ticker == symbol.upper())
    )
    sym = sym_result.scalar_one_or_none()
    if sym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Symbol {symbol} not found")

    tf = _TIMEFRAME_MAP.get(timeframe, TimeframeEnum.D1)

    result = await session.execute(
        select(OHLCV)
        .where(OHLCV.symbol_id == sym.id, OHLCV.timeframe == tf)
        .order_by(desc(OHLCV.time))
        .limit(bars)
    )
    rows = list(reversed(result.scalars().all()))

    if rows:
        df = _rows_to_df(rows)
    elif tf == TimeframeEnum.W1:
        # Fallback: aggregate daily → weekly when no native weekly data
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
        if len(df) > bars:
            df = df.tail(bars).reset_index(drop=True)
        log.info(
            "%s: aggregated %d daily → %d weekly bars for chart",
            symbol, len(daily_rows), len(df),
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No OHLCV data for {symbol}. Trigger a data refresh first.",
        )

    if df.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No OHLCV data for {symbol}. Trigger a data refresh first.",
        )

    # Format date strings (YYYY-MM-DD) for lightweight-charts
    date_strs = [t.strftime("%Y-%m-%d") for t in pd.to_datetime(df["time"])]
    n = len(df)

    out_bars = [
        {
            "time": date_strs[i],
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
            {"time": date_strs[i], "value": round(float(ema_df[col].iloc[i]), 4)}
            for i in range(n)
            if pd.notna(ema_df[col].iloc[i])
        ]

    # Supertrend overlay
    supertrend_out: list[dict[str, Any]] = []
    try:
        st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
        if st is not None and not st.empty:
            val_col = next(
                (c for c in st.columns if c.startswith("SUPERT_")
                 and not any(c.startswith(p) for p in ("SUPERTd_", "SUPERTl_", "SUPERTu_"))),
                None,
            )
            dir_col = next((c for c in st.columns if c.startswith("SUPERTd_")), None)
            if val_col and dir_col:
                for i in range(n):
                    val = st[val_col].iloc[i]
                    direction = st[dir_col].iloc[i]
                    if pd.notna(val) and pd.notna(direction):
                        supertrend_out.append({
                            "time": date_strs[i],
                            "value": round(float(val), 4),
                            "direction": int(direction),
                        })
    except Exception as exc:
        log.warning("Supertrend computation failed for %s: %s", symbol, exc)

    return {
        "symbol": symbol.upper(),
        "bars": out_bars,
        "overlays": {
            "ema_21": _ema_overlay("ema_21"),
            "ema_50": _ema_overlay("ema_50"),
            "ema_200": _ema_overlay("ema_200"),
            "supertrend": supertrend_out,
        },
    }
