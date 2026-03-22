"""Backtest API endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.parameter_sweep import SweepConfig, run_sweep_sync
from app.backtesting.results import BacktestResult
from app.backtesting.runner import materialize_yolo_detections, run_backtest_sync
from app.backtesting.strategies import create_strategy
from app.db.session import get_session
from app.models import OHLCV, BacktestResultModel, PatternDetection, Symbol
from app.models.enums import TimeframeEnum
from app.schemas.backtests import (
    BacktestHistoryItem,
    BacktestRequest,
    BacktestResponse,
    SweepRequest,
    SweepResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtests", tags=["backtests"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _fetch_ohlcv(
    session: AsyncSession, symbol: str, timeframe: str, start: date, end: date
) -> tuple[pd.DataFrame, int]:
    """Fetch OHLCV data from DB. Returns (DataFrame, symbol_id)."""
    # Resolve ticker string to symbol_id
    sym_result = await session.execute(select(Symbol).where(Symbol.ticker == symbol))
    sym = sym_result.scalar_one_or_none()
    if not sym:
        raise HTTPException(status_code=404, detail=f"Symbol not found: {symbol}")

    # Map timeframe string to enum
    try:
        tf_enum = TimeframeEnum(timeframe)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}")

    query = (
        select(OHLCV)
        .where(OHLCV.symbol_id == sym.id)
        .where(OHLCV.timeframe == tf_enum)
        .where(OHLCV.time >= start)
        .where(OHLCV.time <= end)
        .order_by(OHLCV.time)
    )
    result = await session.execute(query)
    rows = result.scalars().all()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No OHLCV data found for {symbol}")

    df = pd.DataFrame(
        [
            {
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": int(r.volume),
            }
            for r in rows
        ],
        index=pd.DatetimeIndex([r.time for r in rows]),
    )

    return df, sym.id


async def _fetch_yolo_detections(
    session: AsyncSession, symbol_id: int, start: date, end: date
) -> list[dict]:
    """Fetch pre-computed YOLO pattern detections from DB."""
    query = (
        select(PatternDetection)
        .where(PatternDetection.symbol_id == symbol_id)
        .where(PatternDetection.detected_at >= start)
        .where(PatternDetection.detected_at <= end)
    )
    result = await session.execute(query)
    rows = result.scalars().all()
    return [
        {
            "pattern_name": r.pattern_name,
            "confidence": float(r.confidence),
            "bar_end": r.detected_at,
            "direction": r.direction.value if hasattr(r.direction, "value") else str(r.direction),
        }
        for r in rows
    ]


def _result_to_response(result: BacktestResult, db_id: int | None = None) -> BacktestResponse:
    """Convert BacktestResult to API response."""
    return BacktestResponse(
        id=db_id,
        stats={
            "total_return_pct": result.total_return_pct,
            "cagr_pct": result.cagr_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "max_drawdown_pct": result.max_drawdown_pct,
            "max_drawdown_duration_days": result.max_drawdown_duration_days,
            "win_rate_pct": result.win_rate_pct,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades,
            "avg_trade_pct": result.avg_trade_pct,
            "avg_win_pct": result.avg_win_pct,
            "avg_loss_pct": result.avg_loss_pct,
        },
        equity_curve=result.equity_curve,
        drawdown_curve=result.drawdown_curve,
        trades=result.trades,
        benchmark_return_pct=result.benchmark_return_pct,
        benchmark_sharpe=result.benchmark_sharpe,
    )


async def _save_result(session: AsyncSession, req: BacktestRequest, result: BacktestResult) -> int:
    """Persist a backtest result to the database."""
    model = BacktestResultModel(
        symbol=req.symbol,
        timeframe=req.timeframe,
        start_date=req.start_date,
        end_date=req.end_date,
        strategy=req.strategy_type,
        parameters=req.parameters,
        stats={
            "total_return_pct": result.total_return_pct,
            "cagr_pct": result.cagr_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "max_drawdown_pct": result.max_drawdown_pct,
            "max_drawdown_duration_days": result.max_drawdown_duration_days,
            "win_rate_pct": result.win_rate_pct,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades,
            "avg_trade_pct": result.avg_trade_pct,
            "avg_win_pct": result.avg_win_pct,
            "avg_loss_pct": result.avg_loss_pct,
            "benchmark_return_pct": result.benchmark_return_pct,
            "benchmark_sharpe": result.benchmark_sharpe,
        },
        equity=result.equity_curve,
        drawdown=result.drawdown_curve,
        trades=result.trades,
    )
    session.add(model)
    await session.flush()
    return model.id


@router.post("/run", response_model=BacktestResponse)
async def run_backtest(req: BacktestRequest, session: SessionDep):
    """Run a single backtest and return results."""
    logger.info(
        "Backtest request: strategy=%s, symbol=%s, timeframe=%s, params=%s",
        req.strategy_type,
        req.symbol,
        req.timeframe,
        req.parameters,
    )
    strategy = create_strategy(req.strategy_type, req.parameters)
    df, symbol_id = await _fetch_ohlcv(
        session, req.symbol, req.timeframe, req.start_date, req.end_date
    )

    # Fetch YOLO detections if needed
    if req.strategy_type == "yolo_pattern":
        detections = await _fetch_yolo_detections(session, symbol_id, req.start_date, req.end_date)
        materialize_yolo_detections(df, detections)

    result = await asyncio.to_thread(
        run_backtest_sync,
        df=df,
        strategy=strategy,
        initial_capital=req.initial_capital,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
    )
    result.config.symbol = req.symbol
    result.config.timeframe = req.timeframe

    db_id = await _save_result(session, req, result)
    await session.commit()

    return _result_to_response(result, db_id)


@router.post("/sweep", response_model=SweepResponse)
async def run_sweep(req: SweepRequest, session: SessionDep):
    """Run a parameter sweep and return all results."""
    strategy = create_strategy(req.strategy_type, req.parameters)
    df, _symbol_id = await _fetch_ohlcv(
        session, req.symbol, req.timeframe, req.start_date, req.end_date
    )

    sweep_config = SweepConfig(
        strategy=strategy,
        param_axes=req.param_axes,
        metric=req.metric,
        initial_capital=req.initial_capital,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
    )

    sweep_result = await asyncio.to_thread(run_sweep_sync, df=df, sweep_config=sweep_config)

    responses = [_result_to_response(r) for r in sweep_result.results]
    best_idx = (
        sweep_result.results.index(sweep_result.best_result) if sweep_result.best_result else 0
    )

    return SweepResponse(
        results=responses,
        best_index=best_idx,
        heatmap_data=sweep_result.heatmap_data,
    )


@router.get("/history", response_model=list[BacktestHistoryItem])
async def get_history(session: SessionDep):
    """List the 20 most recent backtest results."""
    query = select(BacktestResultModel).order_by(desc(BacktestResultModel.created_at)).limit(20)
    result = await session.execute(query)
    rows = result.scalars().all()
    return [
        BacktestHistoryItem(
            id=r.id,
            created_at=r.created_at.isoformat(),
            symbol=r.symbol,
            timeframe=r.timeframe,
            strategy=r.strategy,
            total_return_pct=r.stats.get("total_return_pct", 0),
            sharpe_ratio=r.stats.get("sharpe_ratio", 0),
            total_trades=r.stats.get("total_trades", 0),
        )
        for r in rows
    ]


@router.get("/{backtest_id}", response_model=BacktestResponse)
async def get_backtest(backtest_id: int, session: SessionDep):
    """Get a stored backtest result by ID."""
    result = await session.get(BacktestResultModel, backtest_id)
    if not result:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return BacktestResponse(
        id=result.id,
        stats=result.stats,
        equity_curve=result.equity,
        drawdown_curve=result.drawdown,
        trades=result.trades,
        benchmark_return_pct=result.stats.get("benchmark_return_pct", 0),
        benchmark_sharpe=result.stats.get("benchmark_sharpe", 0),
    )


@router.delete("/{backtest_id}")
async def delete_backtest(backtest_id: int, session: SessionDep):
    """Delete a stored backtest result."""
    result = await session.get(BacktestResultModel, backtest_id)
    if not result:
        raise HTTPException(status_code=404, detail="Backtest not found")
    await session.delete(result)
    await session.commit()
    return {"status": "deleted"}
