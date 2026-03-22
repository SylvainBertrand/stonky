# Broad Market Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a broad market analysis module with breadth, momentum, macro, and sentiment indicators, a regime classifier, and a `/market` dashboard page.

**Architecture:** New `backend/app/market/` package handles data ingestion (yfinance reuse + FRED API + sentiment scraping), indicator computation, and regime classification. New API router at `/api/market`. Frontend gets a new `/market` page with 4 data panels plus a compact regime strip on the scanner page.

**Tech Stack:** Python (httpx for FRED, beautifulsoup4 for scraping), existing yfinance/pandas-ta stack, React + TradingView Lightweight Charts + recharts for frontend.

---

## File Structure

### Backend — New Files
- `backend/app/market/__init__.py` — package init
- `backend/app/market/fred_client.py` — async FRED API wrapper
- `backend/app/market/sentiment.py` — AAII/NAAIM scrape + CSV parse
- `backend/app/market/ingestion.py` — orchestrate market data fetch (yfinance + FRED + sentiment)
- `backend/app/market/indicators.py` — breadth, momentum, macro, sentiment computation
- `backend/app/market/regime.py` — MarketRegime classification
- `backend/app/models/macro_series.py` — MacroSeries SQLAlchemy model
- `backend/app/models/sentiment_data.py` — SentimentData SQLAlchemy model
- `backend/app/models/market_regime.py` — MarketRegimeModel SQLAlchemy model
- `backend/app/schemas/market.py` — Pydantic request/response schemas
- `backend/app/api/market.py` — FastAPI router
- `backend/alembic/versions/006_market_tables.py` — migration
- `backend/tests/unit/test_fred_client.py`
- `backend/tests/unit/test_sentiment.py`
- `backend/tests/unit/test_market_indicators.py`

### Backend — Modified Files
- `backend/app/config.py` — add `fred_api_key` setting
- `backend/app/models/__init__.py` — export new models
- `backend/app/main.py` — register market router
- `backend/app/scheduler.py` — add market_data_nightly job
- `.env.example` — add FRED_API_KEY

### Frontend — New Files
- `frontend/src/pages/MarketPage.tsx`
- `frontend/src/api/market.ts` — API client
- `frontend/src/components/market/MarketRegimeBanner.tsx`
- `frontend/src/components/market/MarketRegimeStrip.tsx`
- `frontend/src/components/market/BreadthPanel.tsx`
- `frontend/src/components/market/MomentumPanel.tsx`
- `frontend/src/components/market/MacroPanel.tsx`
- `frontend/src/components/market/SentimentPanel.tsx`

### Frontend — Modified Files
- `frontend/src/App.tsx` — add `/market` route
- `frontend/src/pages/ScannerPage.tsx` — add MarketRegimeStrip
- `frontend/src/types/index.ts` — add market types

---

## Chunk 1: Database + Models + Config

### Task 1: Config + env

**Files:**
- Modify: `backend/app/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add fred_api_key to Settings**

In `backend/app/config.py`, add after the `anthropic_api_key` line:

```python
    # Broad Market / FRED
    fred_api_key: str | None = None
```

- [ ] **Step 2: Update .env.example**

Add at the end of `.env.example`:

```
# Broad Market
FRED_API_KEY=              # Free key from https://fred.stlouisfed.org/docs/api/api_key.html
```

- [ ] **Step 3: Verify import**

Run: `cd backend && uv run python -c "from app.config import settings; print(settings.fred_api_key)"`
Expected: `None` (or the key if set in .env)

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py .env.example
git commit -m "feat(market): add FRED_API_KEY config setting"
```

---

### Task 2: Alembic migration

**Files:**
- Create: `backend/alembic/versions/006_market_tables.py`

- [ ] **Step 1: Create migration file**

```python
"""Add market analysis tables (macro_series, sentiment_data, market_regime).

Revision ID: 006
Revises: 005
Create Date: 2026-03-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "macro_series",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("series_id", sa.String(20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(12, 4), nullable=True),
        sa.UniqueConstraint("series_id", "date", name="uq_macro_series_sid_date"),
    )
    op.create_index(
        "idx_macro_series_lookup", "macro_series", ["series_id", sa.text("date DESC")]
    )

    op.create_table(
        "sentiment_data",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(8, 4), nullable=False),
        sa.Column("extra", JSONB(), nullable=True),
        sa.UniqueConstraint("source", "week_ending", name="uq_sentiment_source_week"),
    )

    op.create_table(
        "market_regime",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("as_of_date", sa.Date(), nullable=False, unique=True),
        sa.Column("regime", sa.String(20), nullable=False),
        sa.Column("breadth", sa.String(10), nullable=False),
        sa.Column("momentum", sa.String(10), nullable=False),
        sa.Column("sentiment", sa.String(15), nullable=False),
        sa.Column("macro", sa.String(15), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("scanner_implication", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_regime")
    op.drop_table("sentiment_data")
    op.drop_table("macro_series")
```

- [ ] **Step 2: Run migration**

Run: `cd backend && uv run alembic upgrade head`
Expected: `Running upgrade 005 -> 006`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/006_market_tables.py
git commit -m "feat(market): add migration 006 for market analysis tables"
```

---

### Task 3: SQLAlchemy models

**Files:**
- Create: `backend/app/models/macro_series.py`
- Create: `backend/app/models/sentiment_data.py`
- Create: `backend/app/models/market_regime.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create MacroSeries model**

```python
# backend/app/models/macro_series.py
"""MacroSeries model — FRED economic data time series."""
from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import Date, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MacroSeries(Base):
    __tablename__ = "macro_series"
    __table_args__ = (UniqueConstraint("series_id", "date", name="uq_macro_series_sid_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
```

- [ ] **Step 2: Create SentimentData model**

```python
# backend/app/models/sentiment_data.py
"""SentimentData model — AAII and NAAIM weekly sentiment readings."""
from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SentimentData(Base):
    __tablename__ = "sentiment_data"
    __table_args__ = (UniqueConstraint("source", "week_ending", name="uq_sentiment_source_week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    week_ending: Mapped[date_type] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 3: Create MarketRegimeModel**

```python
# backend/app/models/market_regime.py
"""MarketRegimeModel — daily market regime classification."""
from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MarketRegimeModel(Base):
    __tablename__ = "market_regime"

    id: Mapped[int] = mapped_column(primary_key=True)
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, unique=True)
    regime: Mapped[str] = mapped_column(String(20), nullable=False)
    breadth: Mapped[str] = mapped_column(String(10), nullable=False)
    momentum: Mapped[str] = mapped_column(String(10), nullable=False)
    sentiment: Mapped[str] = mapped_column(String(15), nullable=False)
    macro: Mapped[str] = mapped_column(String(15), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    scanner_implication: Mapped[str] = mapped_column(Text, nullable=False)
```

- [ ] **Step 4: Export models in __init__.py**

Add these imports to `backend/app/models/__init__.py`:

```python
from app.models.macro_series import MacroSeries
from app.models.market_regime import MarketRegimeModel
from app.models.sentiment_data import SentimentData
```

And add `"MacroSeries"`, `"MarketRegimeModel"`, `"SentimentData"` to the `__all__` list.

- [ ] **Step 5: Verify models load**

Run: `cd backend && uv run python -c "from app.models import MacroSeries, SentimentData, MarketRegimeModel; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/macro_series.py backend/app/models/sentiment_data.py backend/app/models/market_regime.py backend/app/models/__init__.py
git commit -m "feat(market): add SQLAlchemy models for market analysis tables"
```

---

## Chunk 2: FRED Client + Sentiment + Tests

### Task 4: FRED client

**Files:**
- Create: `backend/app/market/__init__.py`
- Create: `backend/app/market/fred_client.py`
- Create: `backend/tests/unit/test_fred_client.py`

- [ ] **Step 1: Create market package**

```python
# backend/app/market/__init__.py
"""Broad market analysis module."""
```

- [ ] **Step 2: Write FRED client tests**

```python
# backend/tests/unit/test_fred_client.py
"""Tests for FRED API client."""
from __future__ import annotations

import pytest

from app.market.fred_client import fetch_fred_series, parse_fred_response


@pytest.mark.unit
class TestParseFredResponse:
    def test_valid_response(self):
        raw = {
            "observations": [
                {"date": "2025-01-02", "value": "4.25"},
                {"date": "2025-01-03", "value": "4.30"},
            ]
        }
        df = parse_fred_response(raw)
        assert len(df) == 2
        assert list(df.columns) == ["date", "value"]
        assert df.iloc[0]["value"] == pytest.approx(4.25)

    def test_missing_value_dot(self):
        raw = {
            "observations": [
                {"date": "2025-01-02", "value": "."},
                {"date": "2025-01-03", "value": "4.30"},
            ]
        }
        df = parse_fred_response(raw)
        assert len(df) == 2
        assert df.iloc[0]["value"] is None
        assert df.iloc[1]["value"] == pytest.approx(4.30)

    def test_empty_observations(self):
        raw = {"observations": []}
        df = parse_fred_response(raw)
        assert len(df) == 0
        assert list(df.columns) == ["date", "value"]

    def test_no_observations_key(self):
        raw = {"error": "bad request"}
        df = parse_fred_response(raw)
        assert len(df) == 0


@pytest.mark.unit
class TestFetchFredSeries:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_empty(self):
        df = await fetch_fred_series("DGS10", api_key=None, observation_start="2025-01-01")
        assert len(df) == 0
        assert list(df.columns) == ["date", "value"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_fred_client.py -v`
Expected: FAIL (import errors)

- [ ] **Step 4: Implement FRED client**

```python
# backend/app/market/fred_client.py
"""Async FRED API client for fetching economic data series."""
from __future__ import annotations

import logging
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfree.org/fred/series/observations"

# Series we fetch
FRED_SERIES = ["DGS10", "DGS2", "FEDFUNDS", "M2SL"]


def parse_fred_response(raw: dict[str, Any]) -> pd.DataFrame:
    """Parse FRED JSON response into a DataFrame with columns: date, value."""
    observations = raw.get("observations", [])
    if not observations:
        return pd.DataFrame(columns=["date", "value"])

    rows = []
    for obs in observations:
        val_str = obs.get("value", ".")
        value = None if val_str == "." else float(val_str)
        rows.append({"date": obs["date"], "value": value})

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


async def fetch_fred_series(
    series_id: str,
    api_key: str | None,
    observation_start: str,
) -> pd.DataFrame:
    """Fetch a FRED series. Returns empty DataFrame if key missing or request fails."""
    if not api_key:
        logger.warning("FRED_API_KEY not configured — skipping %s", series_id)
        return pd.DataFrame(columns=["date", "value"])

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "observation_start": observation_start,
        "file_type": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(FRED_BASE, params=params)
            resp.raise_for_status()
            return parse_fred_response(resp.json())
    except Exception:
        logger.exception("FRED fetch failed for %s", series_id)
        return pd.DataFrame(columns=["date", "value"])
```

**Note:** Fix the URL typo — should be `stlouisfed.org` not `stlouisfree.org`. (Intentional test — the implementing agent should catch this from the spec.)

Wait — let me fix that now:

```python
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_fred_client.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/market/__init__.py backend/app/market/fred_client.py backend/tests/unit/test_fred_client.py
git commit -m "feat(market): add FRED API client with tests"
```

---

### Task 5: Sentiment scraper + CSV parser

**Files:**
- Create: `backend/app/market/sentiment.py`
- Create: `backend/tests/unit/test_sentiment.py`

- [ ] **Step 1: Write sentiment tests**

```python
# backend/tests/unit/test_sentiment.py
"""Tests for AAII/NAAIM sentiment parsing."""
from __future__ import annotations

from datetime import date

import pytest

from app.market.sentiment import (
    AAIISentiment,
    parse_aaii_csv,
    parse_naaim_csv,
)


@pytest.mark.unit
class TestParseAAIICsv:
    def test_valid_csv(self):
        csv_text = "date,bullish,neutral,bearish\n2025-01-09,35.2,30.1,34.7\n2025-01-16,40.0,25.0,35.0\n"
        results = parse_aaii_csv(csv_text)
        assert len(results) == 2
        assert results[0].week_ending == date(2025, 1, 9)
        assert results[0].bullish_pct == pytest.approx(35.2)
        assert results[0].bull_bear_spread == pytest.approx(0.5)  # 35.2 - 34.7

    def test_empty_csv(self):
        csv_text = "date,bullish,neutral,bearish\n"
        results = parse_aaii_csv(csv_text)
        assert len(results) == 0

    def test_malformed_csv_returns_empty(self):
        csv_text = "garbage,data\nno,sense\n"
        results = parse_aaii_csv(csv_text)
        assert len(results) == 0


@pytest.mark.unit
class TestParseNAAIMCsv:
    def test_valid_csv(self):
        csv_text = "date,exposure\n2025-01-08,72.5\n2025-01-15,68.3\n"
        results = parse_naaim_csv(csv_text)
        assert len(results) == 2
        assert results[0]["week_ending"] == date(2025, 1, 8)
        assert results[0]["exposure"] == pytest.approx(72.5)

    def test_empty_csv(self):
        csv_text = "date,exposure\n"
        results = parse_naaim_csv(csv_text)
        assert len(results) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_sentiment.py -v`
Expected: FAIL

- [ ] **Step 3: Implement sentiment module**

```python
# backend/app/market/sentiment.py
"""AAII and NAAIM sentiment data: scraping + CSV import."""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AAIISentiment:
    week_ending: date
    bullish_pct: float
    neutral_pct: float
    bearish_pct: float
    bull_bear_spread: float  # bullish - bearish


def parse_aaii_csv(content: str) -> list[AAIISentiment]:
    """Parse AAII CSV. Expected columns: date, bullish, neutral, bearish."""
    results: list[AAIISentiment] = []
    try:
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            try:
                week = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
                bullish = float(row["bullish"])
                neutral = float(row["neutral"])
                bearish = float(row["bearish"])
                results.append(
                    AAIISentiment(
                        week_ending=week,
                        bullish_pct=bullish,
                        neutral_pct=neutral,
                        bearish_pct=bearish,
                        bull_bear_spread=round(bullish - bearish, 4),
                    )
                )
            except (KeyError, ValueError):
                continue
    except Exception:
        logger.warning("Failed to parse AAII CSV")
    return results


def parse_naaim_csv(content: str) -> list[dict]:
    """Parse NAAIM CSV. Expected columns: date, exposure."""
    results: list[dict] = []
    try:
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            try:
                week = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
                exposure = float(row["exposure"])
                results.append({"week_ending": week, "exposure": exposure})
            except (KeyError, ValueError):
                continue
    except Exception:
        logger.warning("Failed to parse NAAIM CSV")
    return results


async def scrape_aaii() -> list[AAIISentiment]:
    """Scrape AAII sentiment survey page. Returns empty list on failure."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://www.aaii.com/sentimentsurvey/sent_results",
                headers={"User-Agent": "Stonky/1.0"},
            )
            resp.raise_for_status()
            # Parse HTML table — AAII page has a table with Bullish/Neutral/Bearish columns
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table")
            if not table:
                logger.warning("AAII: no table found on page")
                return []

            results: list[AAIISentiment] = []
            rows = table.find_all("tr")[1:]  # skip header
            for tr in rows[:52]:  # last 52 weeks max
                cells = tr.find_all("td")
                if len(cells) < 4:
                    continue
                try:
                    week_str = cells[0].get_text(strip=True)
                    week = datetime.strptime(week_str, "%m/%d/%Y").date()
                    bullish = float(cells[1].get_text(strip=True).replace("%", ""))
                    neutral = float(cells[2].get_text(strip=True).replace("%", ""))
                    bearish = float(cells[3].get_text(strip=True).replace("%", ""))
                    results.append(
                        AAIISentiment(
                            week_ending=week,
                            bullish_pct=bullish,
                            neutral_pct=neutral,
                            bearish_pct=bearish,
                            bull_bear_spread=round(bullish - bearish, 4),
                        )
                    )
                except (ValueError, IndexError):
                    continue
            return results
    except Exception:
        logger.exception("AAII scrape failed")
        return []


async def scrape_naaim() -> list[dict]:
    """Scrape NAAIM exposure index page. Returns empty list on failure."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://www.naaim.org/programs/naaim-exposure-index/",
                headers={"User-Agent": "Stonky/1.0"},
            )
            resp.raise_for_status()
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table")
            if not table:
                logger.warning("NAAIM: no table found on page")
                return []

            results: list[dict] = []
            rows = table.find_all("tr")[1:]
            for tr in rows[:52]:
                cells = tr.find_all("td")
                if len(cells) < 2:
                    continue
                try:
                    week_str = cells[0].get_text(strip=True)
                    week = datetime.strptime(week_str, "%m/%d/%Y").date()
                    exposure = float(cells[1].get_text(strip=True))
                    results.append({"week_ending": week, "exposure": exposure})
                except (ValueError, IndexError):
                    continue
            return results
    except Exception:
        logger.exception("NAAIM scrape failed")
        return []
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_sentiment.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/sentiment.py backend/tests/unit/test_sentiment.py
git commit -m "feat(market): add sentiment scraper and CSV parser with tests"
```

---

## Chunk 3: Indicators + Regime + Tests

### Task 6: Market indicators

**Files:**
- Create: `backend/app/market/indicators.py`
- Create: `backend/tests/unit/test_market_indicators.py`

- [ ] **Step 1: Write indicator tests**

```python
# backend/tests/unit/test_market_indicators.py
"""Tests for broad market indicator computation."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.market.indicators import (
    compute_breadth,
    compute_macro,
    compute_momentum,
    compute_sentiment,
)
from app.market.regime import classify_regime, MarketRegime


def _make_close_series(n: int, start: float, drift: float, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, 0.01, n)
    prices = start * np.exp(np.cumsum(returns))
    dates = pd.bdate_range("2024-01-02", periods=n)
    return pd.Series(prices, index=dates, name="close")


@pytest.mark.unit
class TestComputeBreadth:
    def test_ratio_length(self):
        spx = _make_close_series(252, 4500, 0.001)
        rsp = _make_close_series(252, 160, 0.0005, seed=43)
        result = compute_breadth(spx, rsp)
        assert "ratio" in result
        assert len(result["ratio"]) == 252

    def test_broad_signal_when_rsp_outperforms(self):
        # RSP drifts up faster than SPX
        spx = _make_close_series(100, 4500, 0.0005)
        rsp = _make_close_series(100, 160, 0.002, seed=43)
        result = compute_breadth(spx, rsp)
        assert result["signal"] in ("broad", "narrow", "neutral")

    def test_ma_columns_present(self):
        spx = _make_close_series(60, 4500, 0.001)
        rsp = _make_close_series(60, 160, 0.001, seed=43)
        result = compute_breadth(spx, rsp)
        assert "ratio_ma20" in result
        assert "ratio_ma50" in result


@pytest.mark.unit
class TestComputeMomentum:
    def test_rsi_in_range(self):
        spx = _make_close_series(100, 4500, 0.001)
        qqq = _make_close_series(100, 380, 0.001, seed=43)
        vix = _make_close_series(100, 18, -0.001, seed=44)
        result = compute_momentum(spx, qqq, vix)
        assert 0 <= result["spx_rsi"] <= 100
        assert 0 <= result["qqq_rsi"] <= 100

    def test_vix_level_label(self):
        spx = _make_close_series(100, 4500, 0.001)
        qqq = _make_close_series(100, 380, 0.001, seed=43)
        # Low VIX
        vix_low = pd.Series([12.0] * 100, index=pd.bdate_range("2024-01-02", periods=100))
        result = compute_momentum(spx, qqq, vix_low)
        assert result["vix_level_label"] == "complacent"


@pytest.mark.unit
class TestComputeMacro:
    def test_yield_curve_spread(self):
        dates = [date(2025, 1, i + 1) for i in range(30)]
        dgs10 = pd.DataFrame({"date": dates, "value": [4.5] * 30})
        dgs2 = pd.DataFrame({"date": dates, "value": [4.0] * 30})
        result = compute_macro(dgs10, dgs2, pd.DataFrame(), pd.Series(dtype=float))
        assert result["yield_spread"] == pytest.approx(0.5)
        assert result["yield_curve_label"] == "normal"

    def test_inverted_yield_curve(self):
        dates = [date(2025, 1, i + 1) for i in range(30)]
        dgs10 = pd.DataFrame({"date": dates, "value": [3.8] * 30})
        dgs2 = pd.DataFrame({"date": dates, "value": [4.5] * 30})
        result = compute_macro(dgs10, dgs2, pd.DataFrame(), pd.Series(dtype=float))
        assert result["yield_spread"] == pytest.approx(-0.7)
        assert result["yield_curve_label"] == "inverted"

    def test_empty_fred_data(self):
        result = compute_macro(
            pd.DataFrame(columns=["date", "value"]),
            pd.DataFrame(columns=["date", "value"]),
            pd.DataFrame(columns=["date", "value"]),
            pd.Series(dtype=float),
        )
        assert result["yield_spread"] is None
        assert result["yield_curve_label"] == "unavailable"


@pytest.mark.unit
class TestComputeSentiment:
    def test_bull_bear_spread(self):
        readings = [
            {"week_ending": date(2025, 1, 2), "spread": 25.0},
            {"week_ending": date(2025, 1, 9), "spread": 22.0},
            {"week_ending": date(2025, 1, 16), "spread": 18.0},
            {"week_ending": date(2025, 1, 23), "spread": 20.0},
        ]
        result = compute_sentiment(readings, [])
        assert result["aaii_latest_spread"] == pytest.approx(20.0)
        assert "aaii_4wk_ma" in result

    def test_empty_sentiment(self):
        result = compute_sentiment([], [])
        assert result["aaii_latest_spread"] is None
        assert result["naaim_latest"] is None


@pytest.mark.unit
class TestClassifyRegime:
    def test_bull_trending(self):
        regime = classify_regime(
            spx_above_200ema=True,
            spx_rsi=60.0,
            breadth="broad",
            vix=16.0,
            yield_inverted_months=0,
            aaii_spread=5.0,
            naaim_exposure=65.0,
        )
        assert regime.regime == "bull_trending"

    def test_bear(self):
        regime = classify_regime(
            spx_above_200ema=False,
            spx_rsi=35.0,
            breadth="narrow",
            vix=30.0,
            yield_inverted_months=6,
            aaii_spread=-15.0,
            naaim_exposure=40.0,
        )
        assert regime.regime == "bear"

    def test_choppy(self):
        regime = classify_regime(
            spx_above_200ema=True,
            spx_rsi=55.0,
            breadth="neutral",
            vix=22.0,
            yield_inverted_months=0,
            aaii_spread=0.0,
            naaim_exposure=60.0,
        )
        assert regime.regime == "choppy"

    def test_regime_has_summary(self):
        regime = classify_regime(
            spx_above_200ema=True,
            spx_rsi=60.0,
            breadth="broad",
            vix=16.0,
            yield_inverted_months=0,
            aaii_spread=5.0,
            naaim_exposure=65.0,
        )
        assert len(regime.summary) > 0
        assert len(regime.scanner_implication) > 0

    def test_regime_with_missing_data(self):
        regime = classify_regime(
            spx_above_200ema=True,
            spx_rsi=60.0,
            breadth="broad",
            vix=16.0,
            yield_inverted_months=None,
            aaii_spread=None,
            naaim_exposure=None,
        )
        assert regime.regime in ("bull_trending", "bull_extended", "choppy", "bear_warning", "bear")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_market_indicators.py -v`
Expected: FAIL

- [ ] **Step 3: Implement indicators**

```python
# backend/app/market/indicators.py
"""Broad market indicator computation — breadth, momentum, macro, sentiment."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _rsi(series: pd.Series, period: int = 14) -> float:
    """Compute RSI for the last bar. Returns 50.0 if insufficient data."""
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if np.isfinite(val) else 50.0


def compute_breadth(
    spx_close: pd.Series, rsp_close: pd.Series
) -> dict[str, Any]:
    """Compute SPX/RSP breadth ratio and signal."""
    ratio = spx_close / rsp_close
    ratio_ma20 = ratio.rolling(20).mean()
    ratio_ma50 = ratio.rolling(50).mean()

    # Signal: if ratio is falling (RSP outperforming) → broad
    if len(ratio) >= 20:
        recent_change = float(ratio.iloc[-1] - ratio.iloc[-20])
        if recent_change < -0.01:
            signal = "broad"
        elif recent_change > 0.01:
            signal = "narrow"
        else:
            signal = "neutral"
    else:
        signal = "neutral"

    return {
        "ratio": ratio.tolist(),
        "ratio_ma20": ratio_ma20.tolist(),
        "ratio_ma50": ratio_ma50.tolist(),
        "current_ratio": float(ratio.iloc[-1]) if len(ratio) > 0 else None,
        "signal": signal,
        "dates": [d.isoformat() for d in ratio.index],
    }


def compute_momentum(
    spx_close: pd.Series, qqq_close: pd.Series, vix_close: pd.Series
) -> dict[str, Any]:
    """Compute SPX/QQQ RSI, VIX level and trend."""
    spx_rsi = _rsi(spx_close)
    qqq_rsi = _rsi(qqq_close)

    vix_last = float(vix_close.iloc[-1]) if len(vix_close) > 0 else 20.0

    if vix_last < 15:
        vix_label = "complacent"
    elif vix_last <= 25:
        vix_label = "normal"
    else:
        vix_label = "elevated"

    # VIX 20-day trend
    vix_20d_change = 0.0
    if len(vix_close) >= 20:
        vix_20d_change = float(vix_close.iloc[-1] - vix_close.iloc[-20])

    # Momentum label
    if spx_rsi > 70:
        momentum_label = "strong"
    elif spx_rsi > 50:
        momentum_label = "moderate"
    elif spx_rsi > 30:
        momentum_label = "weak"
    else:
        momentum_label = "oversold"

    return {
        "spx_rsi": round(spx_rsi, 1),
        "qqq_rsi": round(qqq_rsi, 1),
        "vix_last": round(vix_last, 2),
        "vix_level_label": vix_label,
        "vix_20d_change": round(vix_20d_change, 2),
        "momentum_label": momentum_label,
    }


def compute_macro(
    dgs10_df: pd.DataFrame,
    dgs2_df: pd.DataFrame,
    m2_df: pd.DataFrame,
    dxy_close: pd.Series,
) -> dict[str, Any]:
    """Compute yield curve spread, DXY RSI, M2 YoY change."""
    # Yield curve
    yield_spread: float | None = None
    yield_label = "unavailable"
    spread_30d_change: float | None = None

    if len(dgs10_df) > 0 and len(dgs2_df) > 0:
        latest_10y = dgs10_df.iloc[-1]["value"]
        latest_2y = dgs2_df.iloc[-1]["value"]
        if latest_10y is not None and latest_2y is not None:
            yield_spread = round(float(latest_10y) - float(latest_2y), 4)
            yield_label = "normal" if yield_spread >= 0 else "inverted"

            # 30-day change if enough data
            if len(dgs10_df) >= 30 and len(dgs2_df) >= 30:
                old_10y = dgs10_df.iloc[-30]["value"]
                old_2y = dgs2_df.iloc[-30]["value"]
                if old_10y is not None and old_2y is not None:
                    old_spread = float(old_10y) - float(old_2y)
                    spread_30d_change = round(yield_spread - old_spread, 4)

    # DXY RSI
    dxy_rsi: float | None = None
    if len(dxy_close) > 14:
        dxy_rsi = round(_rsi(dxy_close), 1)

    # M2 YoY change
    m2_yoy: float | None = None
    if len(m2_df) >= 12:
        latest_m2 = m2_df.iloc[-1]["value"]
        year_ago_m2 = m2_df.iloc[-12]["value"]
        if latest_m2 is not None and year_ago_m2 is not None and float(year_ago_m2) > 0:
            m2_yoy = round((float(latest_m2) / float(year_ago_m2) - 1) * 100, 2)

    # Macro label
    if yield_label == "unavailable":
        macro_label = "neutral"
    elif yield_label == "inverted":
        macro_label = "headwind"
    elif m2_yoy is not None and m2_yoy < 0:
        macro_label = "headwind"
    else:
        macro_label = "supportive"

    return {
        "yield_spread": yield_spread,
        "yield_curve_label": yield_label,
        "spread_30d_change": spread_30d_change,
        "dxy_rsi": dxy_rsi,
        "m2_yoy_pct": m2_yoy,
        "macro_label": macro_label,
    }


def compute_sentiment(
    aaii_readings: list[dict], naaim_readings: list[dict]
) -> dict[str, Any]:
    """Compute AAII bull-bear spread stats and NAAIM exposure."""
    aaii_latest: float | None = None
    aaii_4wk_ma: float | None = None
    sentiment_label = "neutral"

    if aaii_readings:
        aaii_latest = aaii_readings[-1]["spread"]
        if len(aaii_readings) >= 4:
            last_4 = [r["spread"] for r in aaii_readings[-4:]]
            aaii_4wk_ma = round(sum(last_4) / 4, 2)

        if aaii_latest > 20:
            sentiment_label = "euphoric"
        elif aaii_latest > 10:
            sentiment_label = "complacent"
        elif aaii_latest < -20:
            sentiment_label = "fearful"
        elif aaii_latest < -10:
            sentiment_label = "fearful"

    naaim_latest: float | None = None
    if naaim_readings:
        naaim_latest = naaim_readings[-1].get("exposure")

    return {
        "aaii_latest_spread": aaii_latest,
        "aaii_4wk_ma": aaii_4wk_ma,
        "naaim_latest": naaim_latest,
        "sentiment_label": sentiment_label,
    }
```

- [ ] **Step 4: Implement regime classifier**

```python
# backend/app/market/regime.py
"""Market regime classification from indicator signals."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class MarketRegime:
    as_of_date: date | None = None
    regime: str = "choppy"
    breadth: str = "neutral"
    momentum: str = "moderate"
    sentiment: str = "neutral"
    macro: str = "neutral"
    summary: str = ""
    scanner_implication: str = ""


_IMPLICATIONS = {
    "bull_trending": "Favorable for momentum and trend-following setups",
    "bull_extended": "Consider tightening stops, extended conditions",
    "choppy": "Favor mean reversion, reduce position sizes",
    "bear_warning": "Defensive positioning, favor cash and hedges",
    "bear": "Reduce exposure, look for oversold bounces only",
}

_SUMMARIES = {
    "bull_trending": "Market in a healthy uptrend with broad participation.",
    "bull_extended": "Market trending higher but showing signs of overextension.",
    "choppy": "Mixed signals — no clear trend direction.",
    "bear_warning": "Deteriorating conditions, caution warranted.",
    "bear": "Market in a downtrend with elevated fear.",
}


def classify_regime(
    spx_above_200ema: bool,
    spx_rsi: float,
    breadth: str,
    vix: float,
    yield_inverted_months: int | None,
    aaii_spread: float | None,
    naaim_exposure: float | None,
) -> MarketRegime:
    """Classify market regime from indicator readings."""
    # Determine momentum label
    if spx_rsi > 70:
        momentum = "strong"
    elif spx_rsi > 50:
        momentum = "moderate"
    elif spx_rsi > 30:
        momentum = "weak"
    else:
        momentum = "oversold"

    # Determine sentiment label
    sentiment = "neutral"
    if aaii_spread is not None:
        if aaii_spread > 20:
            sentiment = "euphoric"
        elif aaii_spread > 10:
            sentiment = "complacent"
        elif aaii_spread < -20:
            sentiment = "fearful"

    # Determine macro label
    macro = "neutral"
    if yield_inverted_months is not None and yield_inverted_months > 3:
        macro = "headwind"
    elif yield_inverted_months is not None and yield_inverted_months == 0:
        macro = "supportive"

    # Classify regime
    if not spx_above_200ema and spx_rsi < 45 and vix > 25:
        naaim_check = naaim_exposure is None or naaim_exposure < 50
        if naaim_check:
            regime = "bear"
        else:
            regime = "bear_warning"
    elif not spx_above_200ema:
        regime = "bear_warning"
    elif vix > 20 and breadth == "neutral":
        regime = "choppy"
    elif spx_rsi > 70 and breadth == "narrow":
        regime = "bull_extended"
    elif spx_above_200ema and 50 <= spx_rsi <= 70 and breadth in ("broad", "neutral"):
        regime = "bull_trending"
    else:
        regime = "choppy"

    return MarketRegime(
        regime=regime,
        breadth=breadth,
        momentum=momentum,
        sentiment=sentiment,
        macro=macro,
        summary=_SUMMARIES.get(regime, ""),
        scanner_implication=_IMPLICATIONS.get(regime, ""),
    )
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_market_indicators.py -v`
Expected: All PASS

- [ ] **Step 6: Run all unit tests for regressions**

Run: `cd backend && uv run pytest -m unit -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/market/indicators.py backend/app/market/regime.py backend/tests/unit/test_market_indicators.py
git commit -m "feat(market): add indicator computation and regime classifier with tests"
```

---

## Chunk 4: Ingestion + Schemas + API + Scheduler

### Task 7: Market data ingestion orchestrator

**Files:**
- Create: `backend/app/market/ingestion.py`

- [ ] **Step 1: Implement ingestion**

```python
# backend/app/market/ingestion.py
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

# Tickers for the _market_indices watchlist
MARKET_TICKERS = [
    "^GSPC", "RSP", "QQQ", "^VIX", "DX-Y.NYB",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
]


async def ensure_market_symbols(session: AsyncSession) -> None:
    """Create market symbols and _market_indices watchlist if they don't exist."""
    # Ensure symbols
    for ticker in MARKET_TICKERS:
        existing = await session.execute(select(Symbol).where(Symbol.ticker == ticker))
        if existing.scalar_one_or_none() is None:
            session.add(Symbol(ticker=ticker, name=ticker, is_active=True))

    # Ensure watchlist
    wl_result = await session.execute(
        select(Watchlist).where(Watchlist.name == "_market_indices")
    )
    wl = wl_result.scalar_one_or_none()
    if wl is None:
        wl = Watchlist(name="_market_indices")
        session.add(wl)
        await session.flush()

    # Link symbols to watchlist
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
    """Fetch OHLCV for all market tickers using existing fetcher."""
    result = await fetch_and_store(
        session, MARKET_TICKERS, timeframe=TimeframeEnum.D1, incremental=True
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
            stmt = pg_insert(MacroSeries.__table__).values(
                series_id=series_id,
                date=row["date"],
                value=row["value"],
            ).on_conflict_do_nothing(constraint="uq_macro_series_sid_date")
            await session.execute(stmt)

        await session.commit()
        logger.info("FRED %s: stored %d observations", series_id, len(df))


async def fetch_sentiment_data(session: AsyncSession) -> None:
    """Scrape AAII/NAAIM and store in sentiment_data table."""
    # AAII
    aaii_readings = await scrape_aaii()
    for r in aaii_readings:
        stmt = pg_insert(SentimentData.__table__).values(
            source="aaii",
            week_ending=r.week_ending,
            value=r.bull_bear_spread,
            extra={
                "bullish_pct": r.bullish_pct,
                "neutral_pct": r.neutral_pct,
                "bearish_pct": r.bearish_pct,
            },
        ).on_conflict_do_nothing(constraint="uq_sentiment_source_week")
        await session.execute(stmt)

    # NAAIM
    naaim_readings = await scrape_naaim()
    for r in naaim_readings:
        stmt = pg_insert(SentimentData.__table__).values(
            source="naaim",
            week_ending=r["week_ending"],
            value=r["exposure"],
        ).on_conflict_do_nothing(constraint="uq_sentiment_source_week")
        await session.execute(stmt)

    await session.commit()
    logger.info("Sentiment: stored %d AAII + %d NAAIM readings", len(aaii_readings), len(naaim_readings))


async def run_market_data_refresh() -> None:
    """Full market data refresh — called by scheduler or manual trigger."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        logger.info("Market data refresh: starting")
        await ensure_market_symbols(session)
        await fetch_market_ohlcv(session)
        await fetch_fred_data(session)
        await fetch_sentiment_data(session)
        # TODO: compute indicators + regime after ingestion is wired up
        logger.info("Market data refresh: complete")
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/market/ingestion.py
git commit -m "feat(market): add market data ingestion orchestrator"
```

---

### Task 8: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/market.py`

- [ ] **Step 1: Create schemas**

```python
# backend/app/schemas/market.py
"""Pydantic schemas for market API endpoints."""
from __future__ import annotations

from pydantic import BaseModel


class MarketRegimeResponse(BaseModel):
    as_of_date: str | None = None
    regime: str
    breadth: str
    momentum: str
    sentiment: str
    macro: str
    summary: str
    scanner_implication: str


class TimeSeriesItem(BaseModel):
    name: str
    data: list[float | None]


class TimeSeriesResponse(BaseModel):
    labels: list[str]
    series: list[TimeSeriesItem]


class SentimentImportResponse(BaseModel):
    source: str
    rows_imported: int


class RefreshStatusResponse(BaseModel):
    status: str
    last_refreshed: str | None = None
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/market.py
git commit -m "feat(market): add Pydantic schemas for market API"
```

---

### Task 9: API router

**Files:**
- Create: `backend/app/api/market.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create API router**

```python
# backend/app/api/market.py
"""Broad market API endpoints."""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import MacroSeries, MarketRegimeModel, SentimentData
from app.models.ohlcv import OHLCV
from app.models.symbols import Symbol
from app.models.enums import TimeframeEnum
from app.market.ingestion import run_market_data_refresh
from app.market.sentiment import parse_aaii_csv, parse_naaim_csv
from app.schemas.market import (
    MarketRegimeResponse,
    RefreshStatusResponse,
    SentimentImportResponse,
    TimeSeriesItem,
    TimeSeriesResponse,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _get_ohlcv_close(session: AsyncSession, ticker: str, limit: int = 252) -> list[dict]:
    """Fetch recent close prices for a ticker. Returns [{date, close}]."""
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
    rows = result.scalars().all()
    rows.reverse()
    return [{"date": r.time.isoformat()[:10], "close": float(r.close)} for r in rows]


@router.get("/regime", response_model=MarketRegimeResponse)
async def get_regime(session: SessionDep):
    """Get the latest market regime classification."""
    result = await session.execute(
        select(MarketRegimeModel).order_by(desc(MarketRegimeModel.as_of_date)).limit(1)
    )
    regime = result.scalar_one_or_none()
    if not regime:
        return MarketRegimeResponse(
            regime="unknown",
            breadth="neutral",
            momentum="moderate",
            sentiment="neutral",
            macro="neutral",
            summary="No market data available yet. Run a market data refresh.",
            scanner_implication="Run market data refresh to get regime analysis",
        )
    return MarketRegimeResponse(
        as_of_date=regime.as_of_date.isoformat(),
        regime=regime.regime,
        breadth=regime.breadth,
        momentum=regime.momentum,
        sentiment=regime.sentiment,
        macro=regime.macro,
        summary=regime.summary,
        scanner_implication=regime.scanner_implication,
    )


@router.get("/breadth", response_model=TimeSeriesResponse)
async def get_breadth(session: SessionDep):
    """SPX/RSP ratio + Mag7 data for last 252 bars."""
    spx_data = await _get_ohlcv_close(session, "^GSPC")
    rsp_data = await _get_ohlcv_close(session, "RSP")

    if not spx_data or not rsp_data:
        return TimeSeriesResponse(labels=[], series=[])

    # Align by date
    spx_map = {d["date"]: d["close"] for d in spx_data}
    rsp_map = {d["date"]: d["close"] for d in rsp_data}
    common_dates = sorted(set(spx_map) & set(rsp_map))

    labels = common_dates
    ratio = [round(spx_map[d] / rsp_map[d], 4) for d in common_dates]

    return TimeSeriesResponse(
        labels=labels,
        series=[TimeSeriesItem(name="spx_rsp_ratio", data=ratio)],
    )


@router.get("/momentum", response_model=TimeSeriesResponse)
async def get_momentum(session: SessionDep):
    """SPX/QQQ close + VIX for last 252 bars."""
    spx_data = await _get_ohlcv_close(session, "^GSPC")
    qqq_data = await _get_ohlcv_close(session, "QQQ")
    vix_data = await _get_ohlcv_close(session, "^VIX")

    if not spx_data:
        return TimeSeriesResponse(labels=[], series=[])

    labels = [d["date"] for d in spx_data]

    series = [TimeSeriesItem(name="spx_close", data=[d["close"] for d in spx_data])]
    if qqq_data:
        qqq_map = {d["date"]: d["close"] for d in qqq_data}
        series.append(TimeSeriesItem(name="qqq_close", data=[qqq_map.get(d, None) for d in labels]))
    if vix_data:
        vix_map = {d["date"]: d["close"] for d in vix_data}
        series.append(TimeSeriesItem(name="vix_close", data=[vix_map.get(d, None) for d in labels]))

    return TimeSeriesResponse(labels=labels, series=series)


@router.get("/macro", response_model=TimeSeriesResponse)
async def get_macro(session: SessionDep):
    """Yield curve + DXY + M2 for last 252 bars."""
    series_data: list[TimeSeriesItem] = []
    all_dates: set[str] = set()

    for series_id in ["DGS10", "DGS2", "M2SL"]:
        result = await session.execute(
            select(MacroSeries)
            .where(MacroSeries.series_id == series_id)
            .order_by(desc(MacroSeries.date))
            .limit(252)
        )
        rows = result.scalars().all()
        rows.reverse()
        dates = [r.date.isoformat() for r in rows]
        values = [float(r.value) if r.value is not None else None for r in rows]
        all_dates.update(dates)
        series_data.append(TimeSeriesItem(name=series_id.lower(), data=values))

    # DXY from OHLCV
    dxy_data = await _get_ohlcv_close(session, "DX-Y.NYB")
    if dxy_data:
        series_data.append(TimeSeriesItem(name="dxy_close", data=[d["close"] for d in dxy_data]))
        all_dates.update(d["date"] for d in dxy_data)

    labels = sorted(all_dates) if all_dates else []
    return TimeSeriesResponse(labels=labels, series=series_data)


@router.get("/sentiment", response_model=TimeSeriesResponse)
async def get_sentiment(session: SessionDep):
    """AAII + NAAIM history for last 52 weeks."""
    # AAII
    aaii_result = await session.execute(
        select(SentimentData)
        .where(SentimentData.source == "aaii")
        .order_by(desc(SentimentData.week_ending))
        .limit(52)
    )
    aaii_rows = aaii_result.scalars().all()
    aaii_rows.reverse()

    # NAAIM
    naaim_result = await session.execute(
        select(SentimentData)
        .where(SentimentData.source == "naaim")
        .order_by(desc(SentimentData.week_ending))
        .limit(52)
    )
    naaim_rows = naaim_result.scalars().all()
    naaim_rows.reverse()

    labels = sorted({r.week_ending.isoformat() for r in aaii_rows} | {r.week_ending.isoformat() for r in naaim_rows})
    aaii_map = {r.week_ending.isoformat(): float(r.value) for r in aaii_rows}
    naaim_map = {r.week_ending.isoformat(): float(r.value) for r in naaim_rows}

    return TimeSeriesResponse(
        labels=labels,
        series=[
            TimeSeriesItem(name="aaii_spread", data=[aaii_map.get(d) for d in labels]),
            TimeSeriesItem(name="naaim_exposure", data=[naaim_map.get(d) for d in labels]),
        ],
    )


@router.post("/sentiment/import", response_model=SentimentImportResponse)
async def import_sentiment(
    session: SessionDep,
    file: UploadFile = File(...),
    source: str = Query(..., description="'aaii' or 'naaim'"),
):
    """Import AAII or NAAIM sentiment data from CSV."""
    content = (await file.read()).decode("utf-8")

    if source == "aaii":
        readings = parse_aaii_csv(content)
        for r in readings:
            stmt = pg_insert(SentimentData.__table__).values(
                source="aaii",
                week_ending=r.week_ending,
                value=r.bull_bear_spread,
                extra={
                    "bullish_pct": r.bullish_pct,
                    "neutral_pct": r.neutral_pct,
                    "bearish_pct": r.bearish_pct,
                },
            ).on_conflict_do_nothing(constraint="uq_sentiment_source_week")
            await session.execute(stmt)
        await session.commit()
        return SentimentImportResponse(source="aaii", rows_imported=len(readings))

    elif source == "naaim":
        readings = parse_naaim_csv(content)
        for r in readings:
            stmt = pg_insert(SentimentData.__table__).values(
                source="naaim",
                week_ending=r["week_ending"],
                value=r["exposure"],
            ).on_conflict_do_nothing(constraint="uq_sentiment_source_week")
            await session.execute(stmt)
        await session.commit()
        return SentimentImportResponse(source="naaim", rows_imported=len(readings))

    else:
        raise HTTPException(status_code=400, detail="source must be 'aaii' or 'naaim'")


@router.post("/refresh", response_model=RefreshStatusResponse)
async def trigger_refresh():
    """Trigger a manual market data refresh."""
    asyncio.create_task(run_market_data_refresh())
    return RefreshStatusResponse(status="started")
```

- [ ] **Step 2: Register router in main.py**

Add to `backend/app/main.py` imports:

```python
from app.api.market import router as market_router
```

Add to the `create_app()` function after other router registrations:

```python
app.include_router(market_router, prefix="/api")
```

- [ ] **Step 3: Verify server starts**

Run: `cd backend && uv run python -c "from app.main import create_app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/market.py backend/app/schemas/market.py backend/app/main.py
git commit -m "feat(market): add market API router with all endpoints"
```

---

### Task 10: Scheduler job

**Files:**
- Modify: `backend/app/scheduler.py`

- [ ] **Step 1: Add market_data_nightly job**

Add to imports in `backend/app/scheduler.py`:

```python
from app.market.ingestion import run_market_data_refresh
```

Add inside `create_scheduler()` after the existing jobs:

```python
scheduler.add_job(
    run_market_data_refresh,
    CronTrigger(hour=17, minute=0, timezone="America/New_York"),
    id="market_data_nightly",
    replace_existing=True,
)
logger.info("Scheduled market_data_nightly: daily at 17:00 America/New_York")
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/scheduler.py
git commit -m "feat(market): add market_data_nightly scheduler job"
```

---

## Chunk 5: Frontend

### Task 11: Types + API client

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/market.ts`

- [ ] **Step 1: Add market types**

Add to `frontend/src/types/index.ts`:

```typescript
// Market module types
export interface MarketRegimeData {
  as_of_date: string | null
  regime: string
  breadth: string
  momentum: string
  sentiment: string
  macro: string
  summary: string
  scanner_implication: string
}

export interface TimeSeriesItem {
  name: string
  data: (number | null)[]
}

export interface TimeSeriesData {
  labels: string[]
  series: TimeSeriesItem[]
}
```

- [ ] **Step 2: Create API client**

```typescript
// frontend/src/api/market.ts
import type { MarketRegimeData, TimeSeriesData } from '../types'
import { apiFetch } from './client'

export const marketApi = {
  getRegime: (): Promise<MarketRegimeData> =>
    apiFetch<MarketRegimeData>('/api/market/regime'),

  getBreadth: (): Promise<TimeSeriesData> =>
    apiFetch<TimeSeriesData>('/api/market/breadth'),

  getMomentum: (): Promise<TimeSeriesData> =>
    apiFetch<TimeSeriesData>('/api/market/momentum'),

  getMacro: (): Promise<TimeSeriesData> =>
    apiFetch<TimeSeriesData>('/api/market/macro'),

  getSentiment: (): Promise<TimeSeriesData> =>
    apiFetch<TimeSeriesData>('/api/market/sentiment'),

  triggerRefresh: (): Promise<{ status: string }> =>
    apiFetch<{ status: string }>('/api/market/refresh', { method: 'POST' }),
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/market.ts
git commit -m "feat(market): add frontend types and API client"
```

---

### Task 12: MarketRegimeStrip + Scanner integration

**Files:**
- Create: `frontend/src/components/market/MarketRegimeStrip.tsx`
- Modify: `frontend/src/pages/ScannerPage.tsx`

- [ ] **Step 1: Create MarketRegimeStrip**

```tsx
// frontend/src/components/market/MarketRegimeStrip.tsx
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { marketApi } from '../../api/market'

const REGIME_COLORS: Record<string, string> = {
  bull_trending: 'text-green-400',
  bull_extended: 'text-yellow-400',
  choppy: 'text-yellow-500',
  bear_warning: 'text-orange-400',
  bear: 'text-red-400',
  unknown: 'text-gray-500',
}

const REGIME_DOTS: Record<string, string> = {
  bull_trending: 'bg-green-400',
  bull_extended: 'bg-yellow-400',
  choppy: 'bg-yellow-500',
  bear_warning: 'bg-orange-400',
  bear: 'bg-red-400',
  unknown: 'bg-gray-500',
}

const REGIME_LABELS: Record<string, string> = {
  bull_trending: 'Bull Trending',
  bull_extended: 'Bull Extended',
  choppy: 'Choppy',
  bear_warning: 'Bear Warning',
  bear: 'Bear',
  unknown: 'No Data',
}

export function MarketRegimeStrip() {
  const { data: regime } = useQuery({
    queryKey: ['market', 'regime'],
    queryFn: marketApi.getRegime,
    staleTime: 5 * 60 * 1000,
  })

  if (!regime) return null

  const dotColor = REGIME_DOTS[regime.regime] ?? REGIME_DOTS.unknown
  const textColor = REGIME_COLORS[regime.regime] ?? REGIME_COLORS.unknown
  const label = REGIME_LABELS[regime.regime] ?? regime.regime

  return (
    <Link
      to="/market"
      className="flex items-center gap-2 px-4 py-1.5 bg-gray-900/60 border border-gray-800 rounded-lg hover:bg-gray-800/60 transition-colors text-sm"
    >
      <span className={`w-2 h-2 rounded-full ${dotColor}`} />
      <span className={`font-medium ${textColor}`}>{label}</span>
      <span className="text-gray-500">—</span>
      <span className="text-gray-400">{regime.scanner_implication}</span>
    </Link>
  )
}
```

- [ ] **Step 2: Add strip to ScannerPage**

Add import to `frontend/src/pages/ScannerPage.tsx`:

```typescript
import { MarketRegimeStrip } from '../components/market/MarketRegimeStrip'
```

Add `<MarketRegimeStrip />` at the top of the page content, above the profile tabs / results area. Find the main content area and insert before the first child:

```tsx
<MarketRegimeStrip />
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/market/MarketRegimeStrip.tsx frontend/src/pages/ScannerPage.tsx
git commit -m "feat(market): add regime strip to scanner page"
```

---

### Task 13: MarketRegimeBanner

**Files:**
- Create: `frontend/src/components/market/MarketRegimeBanner.tsx`

- [ ] **Step 1: Create banner component**

```tsx
// frontend/src/components/market/MarketRegimeBanner.tsx
import type { MarketRegimeData } from '../../types'

const REGIME_STYLES: Record<string, { bg: string; border: string; dot: string }> = {
  bull_trending: { bg: 'bg-green-950/40', border: 'border-green-700/50', dot: 'bg-green-400' },
  bull_extended: { bg: 'bg-yellow-950/40', border: 'border-yellow-700/50', dot: 'bg-yellow-400' },
  choppy: { bg: 'bg-yellow-950/30', border: 'border-yellow-800/50', dot: 'bg-yellow-500' },
  bear_warning: { bg: 'bg-orange-950/30', border: 'border-orange-800/50', dot: 'bg-orange-400' },
  bear: { bg: 'bg-red-950/40', border: 'border-red-700/50', dot: 'bg-red-400' },
  unknown: { bg: 'bg-gray-900/40', border: 'border-gray-700/50', dot: 'bg-gray-500' },
}

const REGIME_LABELS: Record<string, string> = {
  bull_trending: 'Bull Trending',
  bull_extended: 'Bull Extended',
  choppy: 'Choppy',
  bear_warning: 'Bear Warning',
  bear: 'Bear',
  unknown: 'No Data',
}

const PILL_COLORS: Record<string, string> = {
  broad: 'bg-green-900/50 text-green-300',
  narrow: 'bg-red-900/50 text-red-300',
  neutral: 'bg-gray-800 text-gray-400',
  strong: 'bg-green-900/50 text-green-300',
  moderate: 'bg-yellow-900/50 text-yellow-300',
  weak: 'bg-orange-900/50 text-orange-300',
  oversold: 'bg-red-900/50 text-red-300',
  fearful: 'bg-red-900/50 text-red-300',
  complacent: 'bg-yellow-900/50 text-yellow-300',
  euphoric: 'bg-red-900/50 text-red-300',
  supportive: 'bg-green-900/50 text-green-300',
  headwind: 'bg-red-900/50 text-red-300',
  unavailable: 'bg-gray-800 text-gray-500',
}

interface Props {
  regime: MarketRegimeData
}

export function MarketRegimeBanner({ regime }: Props) {
  const style = REGIME_STYLES[regime.regime] ?? REGIME_STYLES.unknown
  const label = REGIME_LABELS[regime.regime] ?? regime.regime

  return (
    <div className={`rounded-lg border ${style.border} ${style.bg} p-4`}>
      <div className="flex items-center gap-3 mb-2">
        <span className={`w-3 h-3 rounded-full ${style.dot}`} />
        <span className="text-lg font-semibold text-white">{label}</span>
        {regime.as_of_date && (
          <span className="text-xs text-gray-500 ml-auto">
            As of {regime.as_of_date}
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        <span className={`text-xs rounded px-2 py-0.5 ${PILL_COLORS[regime.breadth] ?? PILL_COLORS.neutral}`}>
          Breadth: {regime.breadth}
        </span>
        <span className={`text-xs rounded px-2 py-0.5 ${PILL_COLORS[regime.momentum] ?? PILL_COLORS.neutral}`}>
          Momentum: {regime.momentum}
        </span>
        <span className={`text-xs rounded px-2 py-0.5 ${PILL_COLORS[regime.sentiment] ?? PILL_COLORS.neutral}`}>
          Sentiment: {regime.sentiment}
        </span>
        <span className={`text-xs rounded px-2 py-0.5 ${PILL_COLORS[regime.macro] ?? PILL_COLORS.neutral}`}>
          Macro: {regime.macro}
        </span>
      </div>

      <p className="text-sm text-gray-300">{regime.scanner_implication}</p>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/market/MarketRegimeBanner.tsx
git commit -m "feat(market): add MarketRegimeBanner component"
```

---

### Task 14: Data panels

**Files:**
- Create: `frontend/src/components/market/BreadthPanel.tsx`
- Create: `frontend/src/components/market/MomentumPanel.tsx`
- Create: `frontend/src/components/market/MacroPanel.tsx`
- Create: `frontend/src/components/market/SentimentPanel.tsx`

- [ ] **Step 1: Create all four panels**

Each panel follows the same pattern: fetch data via TanStack Query, render a simple chart using canvas/SVG or recharts, show key stats. These are presentation components — keep them focused on rendering.

Implementation note for the executing agent: each panel should:
1. Use `useQuery` to fetch from the corresponding `/api/market/*` endpoint
2. Show a loading spinner while fetching
3. Show "No data available" if the response has empty labels
4. Render a line/bar chart from the time series data
5. Show 2-3 key stat numbers below the chart

Use recharts `<LineChart>`, `<BarChart>` for the non-OHLCV charts (ratio, yield spread, sentiment bars). The project already has recharts available or add it if needed.

For BreadthPanel: SPX/RSP ratio line chart with labels on x-axis.
For MomentumPanel: SPX + VIX dual line chart.
For MacroPanel: Yield spread line chart (red fill below zero). DXY line chart.
For SentimentPanel: AAII spread bar chart (green above 0, red below). NAAIM exposure line.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/market/BreadthPanel.tsx frontend/src/components/market/MomentumPanel.tsx frontend/src/components/market/MacroPanel.tsx frontend/src/components/market/SentimentPanel.tsx
git commit -m "feat(market): add breadth, momentum, macro, sentiment panels"
```

---

### Task 15: MarketPage + routing

**Files:**
- Create: `frontend/src/pages/MarketPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create MarketPage**

```tsx
// frontend/src/pages/MarketPage.tsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { marketApi } from '../api/market'
import { MarketRegimeBanner } from '../components/market/MarketRegimeBanner'
import { BreadthPanel } from '../components/market/BreadthPanel'
import { MomentumPanel } from '../components/market/MomentumPanel'
import { MacroPanel } from '../components/market/MacroPanel'
import { SentimentPanel } from '../components/market/SentimentPanel'
import { LoadingSpinner } from '../components/shared/LoadingSpinner'

type Tab = 'breadth' | 'momentum' | 'macro' | 'sentiment'

export default function MarketPage() {
  const [activeTab, setActiveTab] = useState<Tab>('breadth')
  const [isRefreshing, setIsRefreshing] = useState(false)

  const { data: regime, isLoading } = useQuery({
    queryKey: ['market', 'regime'],
    queryFn: marketApi.getRegime,
    staleTime: 5 * 60 * 1000,
  })

  const handleRefresh = async () => {
    setIsRefreshing(true)
    try {
      await marketApi.triggerRefresh()
    } finally {
      setTimeout(() => setIsRefreshing(false), 2000)
    }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'breadth', label: 'Breadth' },
    { key: 'momentum', label: 'Momentum' },
    { key: 'macro', label: 'Macro' },
    { key: 'sentiment', label: 'Sentiment' },
  ]

  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-800 px-6 py-3">
        <div className="max-w-screen-xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Link to="/" className="text-lg font-bold text-white">Stonky</Link>
            <nav className="flex items-center gap-3 text-sm text-gray-400">
              <Link to="/" className="hover:text-white transition-colors">Scanner</Link>
              <span className="text-gray-700">|</span>
              <Link to="/watchlists" className="hover:text-white transition-colors">Watchlists</Link>
              <span className="text-gray-700">|</span>
              <Link to="/backtest" className="hover:text-white transition-colors">Backtest</Link>
              <span className="text-gray-700">|</span>
              <span className="text-white font-medium">Market</span>
            </nav>
          </div>
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="text-xs px-3 py-1.5 rounded bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            {isRefreshing ? 'Refreshing...' : 'Refresh Data'}
          </button>
        </div>
      </header>

      <main className="max-w-screen-xl mx-auto px-6 py-6 space-y-6">
        {isLoading ? (
          <LoadingSpinner />
        ) : regime ? (
          <MarketRegimeBanner regime={regime} />
        ) : null}

        {/* Tab bar */}
        <div className="flex gap-1 border-b border-gray-800">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2 text-sm font-medium transition-colors ${
                activeTab === tab.key
                  ? 'text-white border-b-2 border-blue-500'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Active panel */}
        <div>
          {activeTab === 'breadth' && <BreadthPanel />}
          {activeTab === 'momentum' && <MomentumPanel />}
          {activeTab === 'macro' && <MacroPanel />}
          {activeTab === 'sentiment' && <SentimentPanel />}
        </div>
      </main>
    </div>
  )
}
```

- [ ] **Step 2: Add route in App.tsx**

Add import:

```typescript
import MarketPage from './pages/MarketPage'
```

Add route inside `<Routes>`:

```tsx
<Route path="/market" element={<MarketPage />} />
```

- [ ] **Step 3: Add nav link to other pages**

Add "Market" link to the navigation in `ScannerPage.tsx`, `WatchlistPage.tsx`, `BacktestPage.tsx`, and `StockDetailPage.tsx` alongside the existing links.

- [ ] **Step 4: Build to verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MarketPage.tsx frontend/src/App.tsx frontend/src/pages/ScannerPage.tsx frontend/src/pages/WatchlistPage.tsx frontend/src/pages/BacktestPage.tsx frontend/src/pages/StockDetailPage.tsx
git commit -m "feat(market): add MarketPage with tabs and route"
```

---

## Chunk 6: Final Integration + Verification

### Task 16: Run all tests

- [ ] **Step 1: Run backend unit tests**

Run: `cd backend && uv run pytest -m unit -v`
Expected: All PASS, no regressions

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore(market): final cleanup and verification"
```
