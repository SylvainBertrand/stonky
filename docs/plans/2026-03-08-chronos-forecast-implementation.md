# Chronos-2 Forecasting Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add probabilistic price forecasting via Chronos-2 as a context layer (not a signal generator) with chart overlay, banner, and scanner integration.

**Architecture:** Nightly background job (same pattern as YOLO scanner) → `forecast_cache` table → REST API → UI overlay + banner. Reuses `scan_runs` for job tracking with `"chronos_forecast"` marker.

**Tech Stack:** chronos-forecasting (HuggingFace), torch, FastAPI, SQLAlchemy 2.0, Alembic, React 18, TradingView Lightweight Charts

---

### Task 1: Add `chronos-forecasting` dependency

**Files:**
- Modify: `backend/pyproject.toml:9-32` (dependencies list)

**Step 1: Add dependency**

In `backend/pyproject.toml`, add to the `dependencies` list after `"huggingface_hub>=0.20.0"`:
```toml
    "chronos-forecasting>=1.0.0",
    "torch>=2.0.0",
```

**Step 2: Install**

Run: `cd backend && uv sync`
Expected: Dependencies install without conflicts.

**Step 3: Commit**

```bash
git add backend/pyproject.toml
git commit -m "chore: add chronos-forecasting dependency for price forecasting"
```

---

### Task 2: Create Alembic migration for `forecast_cache` table

**Files:**
- Create: `backend/alembic/versions/003_add_forecast_cache.py`

**Step 1: Write the migration**

Follow the pattern from `002_nullable_scan_run_fks.py`. Use `revision = "003"`, `down_revision = "002"`.

```python
"""Add forecast_cache table for Chronos-2 price forecasts.

Revision ID: 003
Revises: 002
Create Date: 2026-03-08
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "symbol_id",
            sa.Integer(),
            sa.ForeignKey("symbols.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_bars", sa.Integer(), nullable=False),
        sa.Column("last_bar_date", sa.Date(), nullable=False),
        sa.Column("last_close", sa.Numeric(12, 4), nullable=False),
        sa.Column("median", JSONB(), nullable=False),
        sa.Column("quantile_10", JSONB(), nullable=False),
        sa.Column("quantile_25", JSONB(), nullable=False),
        sa.Column("quantile_75", JSONB(), nullable=False),
        sa.Column("quantile_90", JSONB(), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("direction_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("expected_move_pct", sa.Numeric(7, 4), nullable=False),
    )
    op.create_index(
        "idx_forecast_cache_symbol_tf",
        "forecast_cache",
        ["symbol_id", "timeframe", sa.text("generated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_forecast_cache_symbol_tf", table_name="forecast_cache")
    op.drop_table("forecast_cache")
```

**Step 2: Verify migration syntax**

Run: `cd backend && python -c "from alembic.versions import *; print('OK')"` or just check `alembic heads`:
```bash
cd backend && alembic heads
```
Expected: Shows `003` as head.

**Step 3: Commit**

```bash
git add backend/alembic/versions/003_add_forecast_cache.py
git commit -m "feat: add forecast_cache table migration"
```

---

### Task 3: Create SQLAlchemy model for `forecast_cache`

**Files:**
- Create: `backend/app/models/forecast_cache.py`

**Step 1: Write the model**

Follow the pattern from `backend/app/models/pattern_detections.py:12-46`. Key differences: no enum columns (direction is plain String), JSONB for quantile arrays.

```python
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey

from app.models.base import Base


class ForecastCache(Base):
    __tablename__ = "forecast_cache"
    __table_args__ = (
        Index(
            "idx_forecast_cache_symbol_tf",
            "symbol_id",
            "timeframe",
            "generated_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    horizon_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    last_bar_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_close: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    median: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    quantile_10: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    quantile_25: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    quantile_75: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    quantile_90: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    direction_confidence: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False
    )
    expected_move_pct: Mapped[float] = mapped_column(
        Numeric(7, 4), nullable=False
    )

    symbol: Mapped["Symbol"] = relationship()  # type: ignore[name-defined]
```

**Step 2: Commit**

```bash
git add backend/app/models/forecast_cache.py
git commit -m "feat: add ForecastCache SQLAlchemy model"
```

---

### Task 4: Write unit tests for forecaster module

**Files:**
- Create: `backend/tests/unit/test_forecaster.py`

**Step 1: Write the tests**

Follow the pattern from `backend/tests/unit/test_yolo_screener.py`. Mock the Chronos pipeline — don't download the real model in unit tests.

```python
"""Unit tests for Chronos-2 price forecasting.

Tests cover:
- run_forecast() direction classification
- run_forecast() quantile computation
- run_forecast() edge cases (insufficient data, flat prices)
- Direction confidence calculation
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ohlcv_df(
    n_bars: int = 200,
    start_price: float = 100.0,
    trend: float = 0.001,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    closes = start_price * np.exp(np.cumsum(trend + rng.normal(0, 0.01, n_bars)))
    opens = closes * (1 + rng.normal(0, 0.005, n_bars))
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.01, n_bars))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.01, n_bars))
    volumes = rng.uniform(1e6, 5e6, n_bars)
    dates = pd.bdate_range(end="2026-03-04", periods=n_bars)
    return pd.DataFrame({
        "time": [d.strftime("%Y-%m-%d") for d in dates],
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def _mock_pipeline_predict(closes: np.ndarray, horizon: int, num_samples: int):
    """Return a mock forecast tensor shaped (1, num_samples, horizon).

    Simulates a bullish forecast: slight upward drift from last close.
    """
    import torch

    last = closes[-1]
    drift = np.linspace(0, 0.05, horizon)  # 5% total drift
    noise = np.random.default_rng(42).normal(0, 0.01, (num_samples, horizon))
    samples = last * (1 + drift[np.newaxis, :] + noise)
    return torch.tensor(samples).unsqueeze(0)  # shape (1, num_samples, horizon)


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRunForecast:
    """Tests for run_forecast()."""

    @patch("app.analysis.forecaster._get_pipeline")
    def test_bullish_forecast(self, mock_get_pipeline: MagicMock) -> None:
        """Upward-drifting samples → bullish direction."""
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=200, trend=0.001)
        last_close = df["close"].iloc[-1]

        # Mock pipeline.predict to return upward-drifting samples
        mock_pipeline = MagicMock()
        mock_pipeline.predict.side_effect = (
            lambda context, prediction_length, num_samples, **kw:
                _mock_pipeline_predict(
                    df["close"].values, prediction_length, num_samples
                )
        )
        mock_get_pipeline.return_value = mock_pipeline

        result = run_forecast(df, "TEST", timeframe="1d", horizon=20, num_samples=50)

        assert result is not None
        assert result.symbol == "TEST"
        assert result.direction == "bullish"
        assert result.direction_confidence > 0.5
        assert result.expected_move_pct > 0
        assert len(result.median) == 20
        assert len(result.quantile_10) == 20
        assert len(result.quantile_90) == 20
        assert result.last_close == pytest.approx(last_close, rel=1e-6)

    @patch("app.analysis.forecaster._get_pipeline")
    def test_bearish_forecast(self, mock_get_pipeline: MagicMock) -> None:
        """Downward-drifting samples → bearish direction."""
        import torch
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=200)
        last_close = df["close"].iloc[-1]

        mock_pipeline = MagicMock()
        # Return downward-drifting samples
        def predict_bearish(context, prediction_length, num_samples, **kw):
            drift = np.linspace(0, -0.05, prediction_length)
            noise = np.random.default_rng(42).normal(0, 0.005, (num_samples, prediction_length))
            samples = last_close * (1 + drift[np.newaxis, :] + noise)
            return torch.tensor(samples).unsqueeze(0)

        mock_pipeline.predict.side_effect = predict_bearish
        mock_get_pipeline.return_value = mock_pipeline

        result = run_forecast(df, "TEST", timeframe="1d", horizon=20, num_samples=50)

        assert result is not None
        assert result.direction == "bearish"
        assert result.expected_move_pct < 0

    @patch("app.analysis.forecaster._get_pipeline")
    def test_neutral_forecast(self, mock_get_pipeline: MagicMock) -> None:
        """Flat samples (within ±2%) → neutral direction."""
        import torch
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=200)
        last_close = df["close"].iloc[-1]

        mock_pipeline = MagicMock()
        def predict_flat(context, prediction_length, num_samples, **kw):
            noise = np.random.default_rng(42).normal(0, 0.002, (num_samples, prediction_length))
            samples = last_close * (1 + noise)
            return torch.tensor(samples).unsqueeze(0)

        mock_pipeline.predict.side_effect = predict_flat
        mock_get_pipeline.return_value = mock_pipeline

        result = run_forecast(df, "TEST", timeframe="1d", horizon=20, num_samples=50)

        assert result is not None
        assert result.direction == "neutral"
        assert abs(result.expected_move_pct) <= 2.0

    def test_insufficient_data_returns_none(self) -> None:
        """Less than 50 bars → None."""
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=30)
        result = run_forecast(df, "TEST")
        assert result is None

    @patch("app.analysis.forecaster._get_pipeline")
    def test_quantile_ordering(self, mock_get_pipeline: MagicMock) -> None:
        """Quantiles must be ordered: q10 <= q25 <= median <= q75 <= q90."""
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=200)

        mock_pipeline = MagicMock()
        mock_pipeline.predict.side_effect = (
            lambda context, prediction_length, num_samples, **kw:
                _mock_pipeline_predict(
                    df["close"].values, prediction_length, num_samples
                )
        )
        mock_get_pipeline.return_value = mock_pipeline

        result = run_forecast(df, "TEST", horizon=20, num_samples=50)
        assert result is not None

        for i in range(len(result.median)):
            assert result.quantile_10[i] <= result.quantile_25[i]
            assert result.quantile_25[i] <= result.median[i]
            assert result.median[i] <= result.quantile_75[i]
            assert result.quantile_75[i] <= result.quantile_90[i]

    @patch("app.analysis.forecaster._get_pipeline")
    def test_forecast_result_fields(self, mock_get_pipeline: MagicMock) -> None:
        """ForecastResult has all required fields."""
        from app.analysis.forecaster import run_forecast

        df = _make_ohlcv_df(n_bars=200)

        mock_pipeline = MagicMock()
        mock_pipeline.predict.side_effect = (
            lambda context, prediction_length, num_samples, **kw:
                _mock_pipeline_predict(
                    df["close"].values, prediction_length, num_samples
                )
        )
        mock_get_pipeline.return_value = mock_pipeline

        result = run_forecast(df, "TEST", timeframe="1d", horizon=20, num_samples=50)
        assert result is not None

        assert result.timeframe == "1d"
        assert result.forecast_horizon == 20
        assert result.last_bar_date == "2026-03-04"
        assert result.direction in ("bullish", "bearish", "neutral")
        assert 0.0 <= result.direction_confidence <= 1.0
```

**Step 2: Run the tests (expect them to fail — module doesn't exist yet)**

Run: `cd backend && pytest tests/unit/test_forecaster.py -v`
Expected: ImportError — `app.analysis.forecaster` not found.

**Step 3: Commit**

```bash
git add backend/tests/unit/test_forecaster.py
git commit -m "test: add unit tests for Chronos-2 forecaster"
```

---

### Task 5: Implement `forecaster.py` module

**Files:**
- Create: `backend/app/analysis/forecaster.py`

**Step 1: Write the implementation**

```python
"""Chronos-2 probabilistic price forecasting.

Uses amazon/chronos-t5-small to generate probabilistic forecasts of closing
prices. This is a context layer — it does NOT feed the composite scoring engine.

The model is loaded as a module-level singleton on first use (~250MB download).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import torch

log = logging.getLogger(__name__)

# ── Output contract ──────────────────────────────────────────────────────────

@dataclass
class ForecastResult:
    symbol: str
    timeframe: str
    forecast_horizon: int
    generated_at: str
    last_close: float
    last_bar_date: str
    median: list[float]
    quantile_10: list[float]
    quantile_90: list[float]
    quantile_25: list[float]
    quantile_75: list[float]
    direction: str            # "bullish" | "bearish" | "neutral"
    direction_confidence: float  # 0.0–1.0
    expected_move_pct: float


# ── Model singleton ──────────────────────────────────────────────────────────

_pipeline = None


def _get_pipeline():  # type: ignore[no-untyped-def]
    global _pipeline
    if _pipeline is None:
        from chronos import ChronosPipeline

        log.info("Loading Chronos-2 model (amazon/chronos-t5-small)...")
        _pipeline = ChronosPipeline.from_pretrained(
            "amazon/chronos-t5-small",
            device_map="cpu",
            torch_dtype=torch.float32,
        )
        log.info("Chronos-2 model loaded successfully")
    return _pipeline


# ── Core forecast function ───────────────────────────────────────────────────

MIN_BARS = 50
CONTEXT_WINDOW = 200


def run_forecast(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "1d",
    horizon: int = 20,
    num_samples: int = 50,
) -> ForecastResult | None:
    """Run Chronos-2 forecast on closing prices.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame with at least a 'close' column and a 'time' column.
    symbol : str
        Ticker symbol.
    timeframe : str
        Timeframe identifier (e.g., "1d").
    horizon : int
        Number of bars to forecast.
    num_samples : int
        Number of probabilistic sample trajectories.

    Returns
    -------
    ForecastResult | None
        Forecast result, or None if insufficient data (<50 bars).
    """
    if len(df) < MIN_BARS:
        log.info("Forecast %s: insufficient data (%d bars < %d min)", symbol, len(df), MIN_BARS)
        return None

    # Extract close prices — use last CONTEXT_WINDOW bars
    closes = df["close"].values[-CONTEXT_WINDOW:].astype(np.float64)
    last_close = float(closes[-1])
    last_bar_date = str(df["time"].iloc[-1])

    pipeline = _get_pipeline()

    # Chronos expects a torch tensor context
    context = torch.tensor(closes, dtype=torch.float32).unsqueeze(0)  # (1, T)

    # Run inference
    forecast_samples = pipeline.predict(
        context,
        prediction_length=horizon,
        num_samples=num_samples,
    )  # shape: (1, num_samples, horizon)

    samples = forecast_samples.squeeze(0).numpy()  # (num_samples, horizon)

    # Compute quantiles across samples for each forecast step
    median = np.quantile(samples, 0.50, axis=0).tolist()
    quantile_10 = np.quantile(samples, 0.10, axis=0).tolist()
    quantile_25 = np.quantile(samples, 0.25, axis=0).tolist()
    quantile_75 = np.quantile(samples, 0.75, axis=0).tolist()
    quantile_90 = np.quantile(samples, 0.90, axis=0).tolist()

    # Direction classification
    expected_move = (median[-1] - last_close) / last_close
    expected_move_pct = expected_move * 100

    if expected_move > 0.02:
        direction = "bullish"
    elif expected_move < -0.02:
        direction = "bearish"
    else:
        direction = "neutral"

    # Confidence: fraction of samples agreeing with direction
    final_values = samples[:, -1]
    if direction == "bullish":
        direction_confidence = float(np.mean(final_values > last_close))
    elif direction == "bearish":
        direction_confidence = float(np.mean(final_values < last_close))
    else:
        # For neutral: confidence = how tightly clustered near last_close
        within_band = np.abs(final_values - last_close) / last_close < 0.02
        direction_confidence = float(np.mean(within_band))

    return ForecastResult(
        symbol=symbol,
        timeframe=timeframe,
        forecast_horizon=horizon,
        generated_at=datetime.now(timezone.utc).isoformat(),
        last_close=last_close,
        last_bar_date=last_bar_date,
        median=[round(v, 4) for v in median],
        quantile_10=[round(v, 4) for v in quantile_10],
        quantile_25=[round(v, 4) for v in quantile_25],
        quantile_75=[round(v, 4) for v in quantile_75],
        quantile_90=[round(v, 4) for v in quantile_90],
        direction=direction,
        direction_confidence=round(direction_confidence, 4),
        expected_move_pct=round(expected_move_pct, 4),
    )
```

**Step 2: Run the tests**

Run: `cd backend && pytest tests/unit/test_forecaster.py -v`
Expected: All 6 tests PASS.

**Step 3: Commit**

```bash
git add backend/app/analysis/forecaster.py
git commit -m "feat: implement Chronos-2 forecaster module"
```

---

### Task 6: Create Pydantic schemas for forecast API

**Files:**
- Create: `backend/app/schemas/forecasts.py`

**Step 1: Write the schemas**

Follow pattern from `backend/app/schemas/patterns.py`.

```python
"""Pydantic schemas for the Chronos-2 forecast API."""
from __future__ import annotations

from pydantic import BaseModel


class ForecastQuantiles(BaseModel):
    """Forecast quantile bands."""

    median: list[float]
    quantile_10: list[float]
    quantile_25: list[float]
    quantile_75: list[float]
    quantile_90: list[float]


class ForecastResponse(BaseModel):
    """Chronos-2 forecast response for a single symbol."""

    symbol: str
    timeframe: str
    generated_at: str
    last_bar_date: str
    last_close: float
    horizon_bars: int
    direction: str
    direction_confidence: float
    expected_move_pct: float
    forecast: ForecastQuantiles


class ForecastScanRunResponse(BaseModel):
    """Response from triggering a forecast scan."""

    run_id: int
    status: str
    symbols_queued: int


class ForecastScanStatusResponse(BaseModel):
    """Status of a forecast scan run."""

    run_id: int
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    symbols_scanned: int = 0
    symbols_forecast: int = 0
```

**Step 2: Commit**

```bash
git add backend/app/schemas/forecasts.py
git commit -m "feat: add Pydantic schemas for forecast API"
```

---

### Task 7: Implement forecast background job

**Files:**
- Create: `backend/app/analysis/forecast_scanner.py`

**Step 1: Write the background job**

Follow the pattern from `backend/app/analysis/yolo_scanner.py:155-254`. Reuse `_get_watchlist_symbols` pattern and `scan_runs` tracking with `FORECAST_SCAN_MARKER`.

```python
"""Chronos-2 forecast batch job — runs forecasts for all watchlist symbols.

Runs as a background job (nightly scheduled or manual trigger).
Stores results in the forecast_cache table.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.forecaster import run_forecast
from app.analysis.pipeline import fetch_ohlcv_for_symbol
from app.db.session import AsyncSessionLocal
from app.models.enums import ScanRunStatus, TimeframeEnum
from app.models.forecast_cache import ForecastCache
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem

log = logging.getLogger(__name__)

FORECAST_SCAN_MARKER = "chronos_forecast"
RETENTION_DAYS = 7


async def _get_watchlist_symbols(
    db: AsyncSession, watchlist_id: int | None = None
) -> list[tuple[int, str]]:
    """Return (symbol_id, ticker) pairs for the given or default watchlist."""
    query = (
        select(Symbol.id, Symbol.ticker)
        .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
        .where(Symbol.is_active.is_(True))
    )
    if watchlist_id is not None:
        query = query.where(WatchlistItem.watchlist_id == watchlist_id)
    else:
        query = query.join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id).where(
            Watchlist.is_default.is_(True)
        )
    result = await db.execute(query.distinct())
    return [(row[0], row[1]) for row in result.all()]


async def _purge_old_forecasts(db: AsyncSession, symbol_id: int) -> None:
    """Remove forecasts older than RETENTION_DAYS for a symbol."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    await db.execute(
        delete(ForecastCache).where(
            and_(
                ForecastCache.symbol_id == symbol_id,
                ForecastCache.generated_at < cutoff,
            )
        )
    )


async def run_forecast_scan_all(
    watchlist_id: int | None = None,
    run_id: int | None = None,
) -> None:
    """Run Chronos-2 forecast for all watchlist symbols.

    Parameters
    ----------
    watchlist_id : int | None
        Watchlist to scan; uses default watchlist if None.
    run_id : int | None
        Existing ScanRun ID to use (from API endpoint).
        If None, creates a new ScanRun (for scheduler invocations).
    """
    async with AsyncSessionLocal() as db:
        if run_id is not None:
            scan_run = await db.get(ScanRun, run_id)
            if scan_run is None:
                log.error("Forecast scan: ScanRun %d not found", run_id)
                return
            scan_run.status = ScanRunStatus.RUNNING
            scan_run.started_at = datetime.now(timezone.utc)
            await db.commit()
        else:
            scan_run = ScanRun(
                profile_id=None,
                watchlist_id=watchlist_id,
                status=ScanRunStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
                symbols_scanned=0,
                symbols_scored=0,
                error_message=FORECAST_SCAN_MARKER,
            )
            db.add(scan_run)
            await db.flush()
            run_id = scan_run.id
            await db.commit()

        log.info("Forecast scan run %d: starting", run_id)

    async with AsyncSessionLocal() as db:
        try:
            symbols = await _get_watchlist_symbols(db, watchlist_id)
            if not symbols:
                log.info("Forecast scan run %d: no watchlist symbols, skipping", run_id)
                scan_run = await db.get(ScanRun, run_id)
                if scan_run:
                    scan_run.status = ScanRunStatus.COMPLETED
                    scan_run.completed_at = datetime.now(timezone.utc)
                    scan_run.error_message = FORECAST_SCAN_MARKER
                    await db.commit()
                return

            total_forecast = 0
            scanned = 0
            loop = asyncio.get_event_loop()

            for symbol_id, ticker in symbols:
                try:
                    df = await fetch_ohlcv_for_symbol(
                        symbol_id, ticker, db, TimeframeEnum.D1
                    )
                    if df is None or len(df) < 50:
                        log.info(
                            "Forecast %s: insufficient OHLCV data, skipping", ticker
                        )
                        scanned += 1
                        continue

                    # Run forecast in thread pool (CPU-bound)
                    result = await loop.run_in_executor(
                        None, run_forecast, df, ticker, "1d", 20, 50
                    )

                    if result is None:
                        scanned += 1
                        continue

                    # Store result
                    forecast_row = ForecastCache(
                        symbol_id=symbol_id,
                        timeframe=result.timeframe,
                        generated_at=datetime.now(timezone.utc),
                        horizon_bars=result.forecast_horizon,
                        last_bar_date=datetime.strptime(
                            result.last_bar_date[:10], "%Y-%m-%d"
                        ).date(),
                        last_close=result.last_close,
                        median=result.median,
                        quantile_10=result.quantile_10,
                        quantile_25=result.quantile_25,
                        quantile_75=result.quantile_75,
                        quantile_90=result.quantile_90,
                        direction=result.direction,
                        direction_confidence=result.direction_confidence,
                        expected_move_pct=result.expected_move_pct,
                    )
                    db.add(forecast_row)

                    # Purge old forecasts for this symbol
                    await _purge_old_forecasts(db, symbol_id)

                    total_forecast += 1
                    scanned += 1
                    await db.commit()

                except Exception as exc:
                    log.error("Forecast %s failed: %s", ticker, exc)
                    await db.rollback()

            # Update scan run status
            scan_run = await db.get(ScanRun, run_id)
            if scan_run:
                scan_run.status = ScanRunStatus.COMPLETED
                scan_run.completed_at = datetime.now(timezone.utc)
                scan_run.symbols_scanned = len(symbols)
                scan_run.symbols_scored = total_forecast
                scan_run.error_message = FORECAST_SCAN_MARKER
                await db.commit()

            log.info(
                "Forecast scan run %d: completed. symbols=%d, forecast=%d",
                run_id,
                scanned,
                total_forecast,
            )

        except Exception as exc:
            log.error("Forecast scan run %d failed: %s", run_id, exc)
            try:
                scan_run = await db.get(ScanRun, run_id)
                if scan_run:
                    scan_run.status = ScanRunStatus.FAILED
                    scan_run.completed_at = datetime.now(timezone.utc)
                    scan_run.error_message = f"{FORECAST_SCAN_MARKER}: {str(exc)[:1900]}"
                    await db.commit()
            except Exception as commit_exc:
                log.error(
                    "Forecast scan run %d: failed to record error: %s",
                    run_id,
                    commit_exc,
                )
```

**Step 2: Commit**

```bash
git add backend/app/analysis/forecast_scanner.py
git commit -m "feat: implement forecast batch job (Chronos-2 scanner)"
```

---

### Task 8: Add nightly forecast job to scheduler

**Files:**
- Modify: `backend/app/scheduler.py:76-94`

**Step 1: Add the chronos forecast job**

After the yolo_nightly_scan block (line 90), before the `else:` on line 91, add:

```python
        from app.analysis.forecast_scanner import run_forecast_scan_all

        scheduler.add_job(
            run_forecast_scan_all,
            CronTrigger(
                hour=8,
                minute=0,
                timezone="America/New_York",
            ),
            id="chronos_nightly_forecast",
            replace_existing=True,
        )
        logger.info(
            "Scheduled chronos_nightly_forecast: daily at 08:00 America/New_York"
        )
```

**Step 2: Commit**

```bash
git add backend/app/scheduler.py
git commit -m "feat: add nightly Chronos-2 forecast job to scheduler"
```

---

### Task 9: Create forecast API router

**Files:**
- Create: `backend/app/api/forecasts.py`
- Modify: `backend/app/main.py:10-14,66-70` (import + register router)

**Step 1: Write the API router**

Follow pattern from `backend/app/api/patterns.py`.

```python
"""Chronos-2 Forecast API — probabilistic price forecast endpoints.

Endpoints:
  GET  /api/forecasts/{symbol}    → latest forecast for a symbol
  POST /api/forecasts/scan        → trigger manual forecast scan (background)
  GET  /api/forecasts/scan/status → status of latest forecast scan run
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.forecast_scanner import FORECAST_SCAN_MARKER, run_forecast_scan_all
from app.db.session import get_session
from app.models.enums import ScanRunStatus
from app.models.forecast_cache import ForecastCache
from app.models.scan_runs import ScanRun
from app.models.symbols import Symbol
from app.models.watchlists import Watchlist, WatchlistItem
from app.schemas.forecasts import (
    ForecastQuantiles,
    ForecastResponse,
    ForecastScanRunResponse,
    ForecastScanStatusResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{symbol}", response_model=ForecastResponse | None)
async def get_forecast(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="Timeframe: 1d")] = "1d",
) -> ForecastResponse | None:
    """Return the latest Chronos-2 forecast for a symbol."""
    sym_result = await session.execute(
        select(Symbol.id).where(Symbol.ticker == symbol.upper())
    )
    symbol_id = sym_result.scalar_one_or_none()
    if symbol_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol {symbol} not found",
        )

    result = await session.execute(
        select(ForecastCache)
        .where(
            ForecastCache.symbol_id == symbol_id,
            ForecastCache.timeframe == timeframe,
        )
        .order_by(desc(ForecastCache.generated_at))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    return ForecastResponse(
        symbol=symbol.upper(),
        timeframe=row.timeframe,
        generated_at=row.generated_at.isoformat(),
        last_bar_date=row.last_bar_date.isoformat(),
        last_close=float(row.last_close),
        horizon_bars=row.horizon_bars,
        direction=row.direction,
        direction_confidence=float(row.direction_confidence),
        expected_move_pct=float(row.expected_move_pct),
        forecast=ForecastQuantiles(
            median=row.median,
            quantile_10=row.quantile_10,
            quantile_25=row.quantile_25,
            quantile_75=row.quantile_75,
            quantile_90=row.quantile_90,
        ),
    )


@router.post("/scan", response_model=ForecastScanRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_forecast_scan(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    watchlist_id: Annotated[
        int | None,
        Query(description="Watchlist to scan; defaults to active watchlist"),
    ] = None,
) -> ForecastScanRunResponse:
    """Trigger a manual Chronos-2 forecast scan (background task)."""
    query = (
        select(Symbol.id)
        .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
        .where(Symbol.is_active.is_(True))
    )
    if watchlist_id is not None:
        query = query.where(WatchlistItem.watchlist_id == watchlist_id)
    else:
        query = query.join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id).where(
            Watchlist.is_default.is_(True)
        )
    sym_result = await session.execute(query.distinct())
    symbol_count = len(sym_result.all())

    if symbol_count == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No symbols in watchlist. Add tickers to a watchlist first.",
        )

    scan_run = ScanRun(
        profile_id=None,
        watchlist_id=watchlist_id,
        status=ScanRunStatus.PENDING,
        symbols_scanned=symbol_count,
        symbols_scored=0,
        error_message=FORECAST_SCAN_MARKER,
    )
    session.add(scan_run)
    await session.flush()
    run_id = scan_run.id
    await session.commit()

    log.info(
        "Queued forecast scan run %d: watchlist_id=%s, symbols=%d",
        run_id,
        watchlist_id,
        symbol_count,
    )

    background_tasks.add_task(run_forecast_scan_all, watchlist_id, run_id)
    return ForecastScanRunResponse(
        run_id=run_id,
        status="queued",
        symbols_queued=symbol_count,
    )


@router.get("/scan/status", response_model=ForecastScanStatusResponse)
async def get_forecast_scan_status(
    session: SessionDep,
) -> ForecastScanStatusResponse:
    """Return the status of the most recent forecast scan run."""
    result = await session.execute(
        select(ScanRun)
        .where(ScanRun.error_message.like(f"{FORECAST_SCAN_MARKER}%"))
        .order_by(desc(ScanRun.created_at))
        .limit(1)
    )
    scan_run = result.scalar_one_or_none()

    if scan_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No forecast scan runs found",
        )

    return ForecastScanStatusResponse(
        run_id=scan_run.id,
        status=scan_run.status.value,
        started_at=scan_run.started_at.isoformat() if scan_run.started_at else None,
        completed_at=scan_run.completed_at.isoformat() if scan_run.completed_at else None,
        symbols_scanned=scan_run.symbols_scanned or 0,
        symbols_forecast=scan_run.symbols_scored or 0,
    )
```

**Step 2: Register in main.py**

In `backend/app/main.py`, add import at line 10:
```python
from app.api.forecasts import router as forecasts_router
```

Add router registration after line 70 (`app.include_router(stocks_router, prefix="/api")`):
```python
    app.include_router(forecasts_router, prefix="/api")
```

**Step 3: Commit**

```bash
git add backend/app/api/forecasts.py backend/app/main.py
git commit -m "feat: add forecast API router with GET/POST/status endpoints"
```

---

### Task 10: Add TypeScript types and API client for forecasts

**Files:**
- Modify: `frontend/src/types/index.ts:64-65` (add forecast types after EWDetection)
- Modify: `frontend/src/api/scanner.ts:63` (add forecastsApi)

**Step 1: Add types to `frontend/src/types/index.ts`**

After the `EWDetection` interface (line 64), add:

```typescript
export interface ForecastQuantiles {
  median: number[]
  quantile_10: number[]
  quantile_25: number[]
  quantile_75: number[]
  quantile_90: number[]
}

export interface ForecastData {
  symbol: string
  timeframe: string
  generated_at: string
  last_bar_date: string
  last_close: number
  horizon_bars: number
  direction: 'bullish' | 'bearish' | 'neutral'
  direction_confidence: number
  expected_move_pct: number
  forecast: ForecastQuantiles
}
```

**Step 2: Add API client to `frontend/src/api/scanner.ts`**

After the `patternsApi` object (line 63), add:

```typescript
export const forecastsApi = {
  getForecast: (symbol: string, timeframe = '1d'): Promise<ForecastData | null> =>
    apiFetch<ForecastData | null>(
      `/api/forecasts/${encodeURIComponent(symbol)}?timeframe=${timeframe}`,
    ),

  triggerScan: (watchlistId?: number | null): Promise<ScanRunResponse> => {
    const qs = watchlistId != null ? `?watchlist_id=${watchlistId}` : ''
    return apiFetch<ScanRunResponse>(`/api/forecasts/scan${qs}`, { method: 'POST' })
  },

  getScanStatus: (): Promise<{ run_id: number; status: string; started_at: string | null; completed_at: string | null; symbols_scanned: number; symbols_forecast: number }> =>
    apiFetch('/api/forecasts/scan/status'),
}
```

**Step 3: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/scanner.ts
git commit -m "feat: add TypeScript types and API client for forecasts"
```

---

### Task 11: Create `useForecast` hook

**Files:**
- Create: `frontend/src/hooks/useForecast.ts`

**Step 1: Write the hook**

Follow pattern from `frontend/src/hooks/useEWPatterns.ts`.

```typescript
import { useQuery } from '@tanstack/react-query'
import { forecastsApi } from '../api/scanner'
import type { ForecastData } from '../types'

export function useForecast(symbol: string, timeframe: string = '1d') {
  return useQuery<ForecastData | null>({
    queryKey: ['forecast', symbol, timeframe],
    queryFn: () => forecastsApi.getForecast(symbol, timeframe),
    staleTime: 10 * 60 * 1000,
    enabled: !!symbol,
  })
}
```

**Step 2: Commit**

```bash
git add frontend/src/hooks/useForecast.ts
git commit -m "feat: add useForecast hook"
```

---

### Task 12: Create `ForecastBanner` component

**Files:**
- Create: `frontend/src/components/stock/ForecastBanner.tsx`

**Step 1: Write the component**

Follow pattern from `frontend/src/components/stock/ElliottWaveBanner.tsx`.

```typescript
import type { ForecastData } from '../../types'

interface Props {
  forecast: ForecastData | null | undefined
}

function formatTimeAgo(isoString: string): string {
  const secs = Math.round((Date.now() - new Date(isoString).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}

export function ForecastBanner({ forecast }: Props) {
  if (!forecast) {
    return (
      <div className="flex items-center gap-3 px-3 py-2 rounded bg-gray-800/60 text-xs mb-2 text-gray-500">
        <span className="font-semibold text-gray-400">Chronos-2 Forecast</span>
        <span>Not yet forecasted</span>
      </div>
    )
  }

  const isBullish = forecast.direction === 'bullish'
  const isBearish = forecast.direction === 'bearish'
  const directionLabel = isBullish ? 'Bullish' : isBearish ? 'Bearish' : 'Neutral'
  const directionClass = isBullish
    ? 'text-green-400 bg-green-400/10'
    : isBearish
      ? 'text-red-400 bg-red-400/10'
      : 'text-gray-400 bg-gray-400/10'

  const moveSign = forecast.expected_move_pct >= 0 ? '+' : ''
  const rangeLow = forecast.forecast.quantile_10[forecast.forecast.quantile_10.length - 1]
  const rangeHigh = forecast.forecast.quantile_90[forecast.forecast.quantile_90.length - 1]

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded bg-gray-800/60 text-xs mb-2 flex-wrap">
      <span className="font-semibold text-gray-300">
        Chronos-2 Forecast ({forecast.horizon_bars}d)
      </span>
      <span className={`px-1.5 py-0.5 rounded font-medium ${directionClass}`}>
        {directionLabel}
      </span>
      <span className="text-gray-300">
        {moveSign}{forecast.expected_move_pct.toFixed(1)}% median
      </span>
      <span className="text-gray-500">
        {Math.round(forecast.direction_confidence * 100)}% confidence
      </span>
      <span className="text-gray-500">
        Range: ${rangeLow.toFixed(2)} – ${rangeHigh.toFixed(2)}
      </span>
      <span className="ml-auto text-gray-600">
        {formatTimeAgo(forecast.generated_at)}
      </span>
    </div>
  )
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/stock/ForecastBanner.tsx
git commit -m "feat: add ForecastBanner component"
```

---

### Task 13: Integrate ForecastBanner into StockDetailPage

**Files:**
- Modify: `frontend/src/pages/StockDetailPage.tsx`

**Step 1: Add imports**

At `StockDetailPage.tsx:14` (after ElliottWaveBanner import), add:
```typescript
import { ForecastBanner } from '../components/stock/ForecastBanner'
import { useForecast } from '../hooks/useForecast'
```

**Step 2: Add the hook call**

At line 47 (after the `useEWPatterns` call), add:
```typescript
  const { data: forecastData } = useForecast(symbol, chartTimeframe)
```

**Step 3: Add the banner**

After the ElliottWaveBanner at line 173, add:
```typescript
        {/* Chronos-2 forecast banner */}
        <ForecastBanner forecast={forecastData} />
```

**Step 4: Commit**

```bash
git add frontend/src/pages/StockDetailPage.tsx
git commit -m "feat: integrate ForecastBanner into StockDetailPage"
```

---

### Task 14: Add Forecast toggle to ChartControls

**Files:**
- Modify: `frontend/src/components/stock/ChartControls.tsx`

**Step 1: Add 'forecast' to OverlayKey**

At line 1, change:
```typescript
export type OverlayKey = 'ema21' | 'ema50' | 'ema200' | 'supertrend' | 'volume' | 'patterns' | 'waves'
```
to:
```typescript
export type OverlayKey = 'ema21' | 'ema50' | 'ema200' | 'supertrend' | 'volume' | 'patterns' | 'waves' | 'forecast'
```

**Step 2: Add default value**

At line 4 (`DEFAULT_OVERLAYS`), add `forecast: false`:
```typescript
export const DEFAULT_OVERLAYS: OverlayToggles = {
  ema21: true,
  ema50: true,
  ema200: true,
  supertrend: true,
  volume: true,
  patterns: true,
  waves: true,
  forecast: false,
}
```

**Step 3: Add label**

In `BUTTON_LABELS` (line 26), add:
```typescript
  forecast: 'Forecast',
```

**Step 4: Add to OVERLAY_KEYS**

At line 36, add `'forecast'` to the array:
```typescript
const OVERLAY_KEYS: OverlayKey[] = ['ema21', 'ema50', 'ema200', 'supertrend', 'volume', 'patterns', 'waves', 'forecast']
```

**Step 5: Commit**

```bash
git add frontend/src/components/stock/ChartControls.tsx
git commit -m "feat: add Forecast toggle to chart controls (default off)"
```

---

### Task 15: Add forecast overlay to CandlestickChart

**Files:**
- Modify: `frontend/src/components/stock/CandlestickChart.tsx`

**Step 1: Add ForecastData import**

At line 3, add `ForecastData` to the import:
```typescript
import type { ChartPatternDetection, OHLCVBar, OHLCVResponse, EWWavePoint, ForecastData } from '../../types'
```

**Step 2: Add forecast props**

In the `Props` interface (line 13-20), add:
```typescript
  forecastData?: ForecastData | null
```

**Step 3: Add the `drawForecastOverlay` function**

After the `drawEWOverlay` function (after line 145), add:

```typescript
export function drawForecastOverlay(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  forecast: ForecastData,
  lastBarTime: string,
  timeToCoordinate: (time: string) => number | null,
  priceToCoordinate: (price: number) => number | null,
  bars: OHLCVBar[],
): void {
  ctx.clearRect(0, 0, width, height)

  const { median, quantile_10, quantile_90, quantile_25, quantile_75 } = forecast.forecast
  const horizon = median.length

  // Generate synthetic future timestamps (skip weekends)
  const lastDate = new Date(lastBarTime + 'T00:00:00')
  const futureDates: string[] = []
  let d = new Date(lastDate)
  for (let i = 0; i < horizon; i++) {
    d.setDate(d.getDate() + 1)
    while (d.getDay() === 0 || d.getDay() === 6) {
      d.setDate(d.getDate() + 1)
    }
    futureDates.push(d.toISOString().slice(0, 10))
  }

  // We need pixel positions — estimate bar width from the last two bars
  const lastBarX = timeToCoordinate(lastBarTime)
  if (lastBarX === null) return

  // Estimate bar spacing from the last two bars
  let barSpacing = 8 // fallback
  if (bars.length >= 2) {
    const secondLastX = timeToCoordinate(bars[bars.length - 2].time)
    if (secondLastX !== null) {
      barSpacing = Math.abs(lastBarX - secondLastX)
    }
  }

  // Build coords for each horizon step
  const coords: Array<{ x: number; med: number | null; q10: number | null; q90: number | null; q25: number | null; q75: number | null }> = []
  for (let i = 0; i < horizon; i++) {
    const x = lastBarX + (i + 1) * barSpacing
    coords.push({
      x,
      med: priceToCoordinate(median[i]),
      q10: priceToCoordinate(quantile_10[i]),
      q90: priceToCoordinate(quantile_90[i]),
      q25: priceToCoordinate(quantile_25[i]),
      q75: priceToCoordinate(quantile_75[i]),
    })
  }

  // Determine color based on direction
  const isBullish = forecast.direction === 'bullish'
  const isBearish = forecast.direction === 'bearish'
  const baseColor = isBullish ? '34, 197, 94' : isBearish ? '239, 68, 68' : '156, 163, 175'

  // Draw outer band (q10–q90) with 0.08 alpha
  ctx.fillStyle = `rgba(${baseColor}, 0.08)`
  ctx.beginPath()
  // Top edge (q90, left to right)
  for (let i = 0; i < coords.length; i++) {
    const c = coords[i]
    if (c.q90 === null) continue
    if (i === 0) ctx.moveTo(c.x, c.q90)
    else ctx.lineTo(c.x, c.q90)
  }
  // Bottom edge (q10, right to left)
  for (let i = coords.length - 1; i >= 0; i--) {
    const c = coords[i]
    if (c.q10 === null) continue
    ctx.lineTo(c.x, c.q10)
  }
  ctx.closePath()
  ctx.fill()

  // Draw inner band (q25–q75) with 0.15 alpha
  ctx.fillStyle = `rgba(${baseColor}, 0.15)`
  ctx.beginPath()
  for (let i = 0; i < coords.length; i++) {
    const c = coords[i]
    if (c.q75 === null) continue
    if (i === 0) ctx.moveTo(c.x, c.q75)
    else ctx.lineTo(c.x, c.q75)
  }
  for (let i = coords.length - 1; i >= 0; i--) {
    const c = coords[i]
    if (c.q25 === null) continue
    ctx.lineTo(c.x, c.q25)
  }
  ctx.closePath()
  ctx.fill()

  // Draw median dashed line
  ctx.strokeStyle = `rgba(${baseColor}, 0.7)`
  ctx.lineWidth = 1.5
  ctx.setLineDash([4, 3])
  ctx.beginPath()
  let started = false
  for (const c of coords) {
    if (c.med === null) continue
    if (!started) { ctx.moveTo(c.x, c.med); started = true }
    else ctx.lineTo(c.x, c.med)
  }
  ctx.stroke()
  ctx.setLineDash([])

  // Label at the end of the median line
  const lastCoord = coords[coords.length - 1]
  if (lastCoord.med !== null) {
    const moveSign = forecast.expected_move_pct >= 0 ? '+' : ''
    const label = `${moveSign}${forecast.expected_move_pct.toFixed(1)}% (${forecast.horizon_bars}d)`
    ctx.font = '10px sans-serif'
    ctx.fillStyle = `rgba(${baseColor}, 0.9)`
    ctx.fillText(label, lastCoord.x + 4, lastCoord.med - 4)
  }
}
```

**Step 4: Update the component signature**

At line 149-151, update the destructured props to include `forecastData`:
```typescript
  { data, height = 420, detections, overlays, ewWaves, ewDirection, forecastData },
```

**Step 5: Add forecast canvas in the main useEffect**

After the EW canvas block (after line 352), add a forecast canvas block:

```typescript
    // ── Forecast canvas overlay (z-index: 5) ──────────────────────────────
    let forecastCanvas: HTMLCanvasElement | null = null
    if (forecastData) {
      forecastCanvas = document.createElement('canvas')
      forecastCanvas.style.position = 'absolute'
      forecastCanvas.style.top = '0'
      forecastCanvas.style.left = '0'
      forecastCanvas.style.pointerEvents = 'none'
      forecastCanvas.style.zIndex = '5'
      container.appendChild(forecastCanvas)

      const redrawForecast = () => {
        if (!forecastCanvas) return
        const ctx = forecastCanvas.getContext('2d')
        if (!ctx) return
        forecastCanvas.width = container.clientWidth
        forecastCanvas.height = height
        drawForecastOverlay(
          ctx, forecastCanvas.width, forecastCanvas.height,
          forecastData, data.bars[data.bars.length - 1].time,
          timeToCoord, priceToCoord, data.bars,
        )
      }
      redrawForecast()
      chart.timeScale().subscribeVisibleTimeRangeChange(redrawForecast)
    }
```

**Step 6: Update cleanup**

In the cleanup function (line 362-379), add before the return:
```typescript
      if (forecastCanvas && forecastCanvas.parentNode) {
        forecastCanvas.parentNode.removeChild(forecastCanvas)
      }
```

**Step 7: Add forecastData to useEffect deps**

At line 380, add `forecastData` to the dependency array:
```typescript
  }, [data, height, detections, ewWaves, ewDirection, forecastData])
```

**Step 8: Add forecast visibility toggle**

In the overlay visibility useEffect (around line 398-406), add after the waves block:
```typescript
    // Forecast visibility — use zIndex 5 canvas
    // Find the forecast canvas by its z-index
    if (overlays.forecast !== undefined) {
      const container = containerRef.current
      if (container) {
        const fcCanvas = container.querySelector('canvas[style*="z-index: 5"]') as HTMLCanvasElement | null
        if (fcCanvas) {
          fcCanvas.style.display = overlays.forecast ? '' : 'none'
        }
      }
    }
```

**Step 9: Commit**

```bash
git add frontend/src/components/stock/CandlestickChart.tsx
git commit -m "feat: add forecast overlay to CandlestickChart (shaded bands + median)"
```

---

### Task 16: Pass forecast data to CandlestickChart from StockDetailPage

**Files:**
- Modify: `frontend/src/pages/StockDetailPage.tsx:128-136`

**Step 1: Add forecastData prop**

At the `<CandlestickChart>` usage (line 128-136), add the `forecastData` prop:
```typescript
            <CandlestickChart
              ref={chartRef}
              data={ohlcv}
              height={420}
              detections={detail.chart_patterns ?? []}
              overlays={overlays}
              ewWaves={ewData?.waves ?? null}
              ewDirection={ewData?.direction ?? null}
              forecastData={overlays.forecast ? forecastData : null}
            />
```

**Step 2: Commit**

```bash
git add frontend/src/pages/StockDetailPage.tsx
git commit -m "feat: pass forecast data to chart, gated by forecast toggle"
```

---

### Task 17: Add Forecast column to scanner ResultsTable

**Files:**
- Modify: `frontend/src/components/scanner/ResultsTable.tsx`

**Step 1: Add ForecastData import**

At line 3, add:
```typescript
import type { ForecastData, ScannerResult } from '../../types'
```
(Replace existing `ScannerResult` import.)

**Step 2: Add forecasts prop**

In the `Props` interface (line 15-19), add:
```typescript
  forecasts?: Record<string, ForecastData>
```

**Step 3: Update function signature**

At line 21:
```typescript
export function ResultsTable({ results, activeProfile, hasScanned, forecasts }: Props) {
```

**Step 4: Add column header**

After the EW header (line 66 `<th className="px-3 py-2 text-left">EW</th>`), add:
```typescript
            <th className="px-3 py-2 text-right">Forecast</th>
```

**Step 5: Add column cell**

After the EW cell (before the expand button cell at line 161), add:
```typescript
                  <td className="px-3 py-2.5 text-right">
                    {(() => {
                      const fc = forecasts?.[r.symbol]
                      if (!fc || fc.direction_confidence < 0.6) {
                        return <span className="text-gray-600 text-xs">—</span>
                      }
                      const colorClass = fc.direction === 'bullish'
                        ? 'text-green-400'
                        : fc.direction === 'bearish'
                          ? 'text-red-400'
                          : 'text-gray-400'
                      const arrow = fc.direction === 'bullish' ? '▲' : fc.direction === 'bearish' ? '▼' : '◆'
                      const sign = fc.expected_move_pct >= 0 ? '+' : ''
                      return (
                        <span className={`text-xs font-medium ${colorClass}`}>
                          {arrow} {sign}{fc.expected_move_pct.toFixed(1)}%
                        </span>
                      )
                    })()}
                  </td>
```

**Step 6: Update colSpan**

At line 170, update the colSpan from `10` to `11`:
```typescript
                    <td colSpan={11} className="p-0">
```

**Step 7: Commit**

```bash
git add frontend/src/components/scanner/ResultsTable.tsx
git commit -m "feat: add Forecast column to scanner results table"
```

---

### Task 18: Fetch and pass forecasts in ScannerPage

**Files:**
- Modify: `frontend/src/pages/ScannerPage.tsx`

**Step 1: Add imports**

At line 4, add `forecastsApi` to the import:
```typescript
import { scannerApi, patternsApi, forecastsApi } from '../api/scanner'
```

Add type import:
```typescript
import type { ForecastData } from '../types'
```

**Step 2: Add forecast state and fetching**

Inside the `ScannerPage` component (after `isRefreshing` state at line 31), add:
```typescript
  const [isForecastScanning, setIsForecastScanning] = useState(false)
  const [forecasts, setForecasts] = useState<Record<string, ForecastData>>({})
```

After the results query, add a useEffect to fetch forecasts for each result:
```typescript
  // Fetch forecasts for scanner results
  useEffect(() => {
    if (results.length === 0) return
    const fetchForecasts = async () => {
      const map: Record<string, ForecastData> = {}
      await Promise.all(
        results.map(async (r) => {
          try {
            const fc = await forecastsApi.getForecast(r.symbol)
            if (fc) map[r.symbol] = fc
          } catch { /* forecast not available */ }
        })
      )
      setForecasts(map)
    }
    void fetchForecasts()
  }, [results])
```

**Step 3: Add handleForecastScan**

After the `handleYoloScan` callback (after line 163), add:

```typescript
  const handleForecastScan = useCallback(async () => {
    setIsForecastScanning(true)
    setScanError(null)
    try {
      await forecastsApi.triggerScan(activeWatchlistId)
      const poll = async () => {
        for (let i = 0; i < 120; i++) {
          await new Promise((r) => setTimeout(r, 5000))
          try {
            const status = await forecastsApi.getScanStatus()
            if (status.status === 'completed') {
              void queryClient.invalidateQueries({ queryKey: ['scanner', 'results'] })
              setIsForecastScanning(false)
              return
            }
            if (status.status === 'failed') {
              setScanError('Forecast scan failed — check backend logs.')
              setIsForecastScanning(false)
              return
            }
          } catch {
            // Status endpoint may not exist yet if scan just started
          }
        }
        setScanError('Forecast scan timed out.')
        setIsForecastScanning(false)
      }
      void poll()
    } catch (err) {
      setIsForecastScanning(false)
      setScanError(err instanceof Error ? err.message : 'Forecast scan failed')
    }
  }, [activeWatchlistId, queryClient])
```

**Step 4: Add the "Run Forecasts" button**

After the "Scan Chart Patterns" button (after line 212), add:
```typescript
            <button
              onClick={() => { void handleForecastScan() }}
              disabled={isForecastScanning || isScanning}
              className="flex items-center gap-2 px-3 py-1.5 rounded bg-teal-700 hover:bg-teal-600 disabled:opacity-60 text-xs font-semibold text-white transition-colors"
            >
              {isForecastScanning && <LoadingSpinner size="sm" />}
              {isForecastScanning ? 'Forecasting…' : 'Run Forecasts'}
            </button>
```

**Step 5: Pass forecasts to ResultsTable**

At line 244, add the `forecasts` prop:
```typescript
          <ResultsTable results={results} activeProfile={activeProfile} hasScanned={lastFetched != null} forecasts={forecasts} />
```

**Step 6: Commit**

```bash
git add frontend/src/pages/ScannerPage.tsx
git commit -m "feat: add Run Forecasts button and forecast column to scanner"
```

---

### Task 19: Run all tests and verify no regressions

**Step 1: Run backend unit tests**

Run: `cd backend && pytest tests/unit/ -v`
Expected: All tests pass, including the new `test_forecaster.py`.

**Step 2: Run frontend tests**

Run: `cd frontend && npm test -- --run`
Expected: All tests pass.

**Step 3: Run linting**

Run: `cd backend && ruff check app/ && ruff format --check app/`
Expected: No errors.

**Step 4: Commit any fixes if needed**

---

### Task 20: Final integration verification

**Step 1: Start backend and test endpoints**

```bash
cd backend && alembic upgrade head
cd backend && uvicorn app.main:app --reload
```

**Step 2: Smoke test API**

```bash
curl -X POST http://localhost:8000/api/forecasts/scan
curl http://localhost:8000/api/forecasts/scan/status
# After scan completes:
curl http://localhost:8000/api/forecasts/AAPL
```

**Step 3: Start frontend and verify UI**

```bash
cd frontend && npm run dev
```

Verify:
1. Forecast section appears in stock detail view with direction + expected move
2. Toggling [Forecast] on the chart shows shaded bands extending to the right
3. Scanner table shows forecast column for stocks with high-confidence direction
4. Run Forecasts button triggers job and shows progress

**Step 4: Final commit if any fixes needed**
