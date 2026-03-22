# Broad Market Phase 1 — Design Spec

**Date:** 2026-03-15
**Status:** Approved
**Milestone:** P2 — Breadth + Sentiment Dashboard

---

## 1. Purpose

Add a broad market analysis module to Stonky that provides macro context for individual stock setups. A new `/market` page displays market regime, breadth, momentum, macro, and sentiment data. A compact regime strip on the scanner page bridges the two modules.

This module is **read-only context** — it informs the trader whether broad market conditions are favorable but does not feed the per-stock composite scoring engine.

---

## 2. Data Sources

### yfinance (existing stack)

| Ticker | Description |
|--------|-------------|
| `^GSPC` | S&P 500 (cap-weighted) |
| `RSP` | Equal-weight S&P 500 ETF |
| `QQQ` | Nasdaq 100 ETF |
| `^VIX` | CBOE Volatility Index |
| `DX-Y.NYB` | US Dollar Index |
| `AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `TSLA` | Mag 7 components |

All stored in the existing `symbols` + `ohlcv` tables. A reserved `_market_indices` watchlist groups them. Fetch 2 years of history on first run; daily incremental thereafter.

### FRED API

| Series ID | Description | Frequency |
|-----------|-------------|-----------|
| `DGS10` | 10-Year Treasury yield | Daily |
| `DGS2` | 2-Year Treasury yield | Daily |
| `FEDFUNDS` | Fed Funds Rate | Monthly |
| `M2SL` | M2 Money Supply | Monthly |

FRED API key configured via `FRED_API_KEY` env var. If not set, all FRED fetches return empty DataFrames and log a warning — the macro panel shows "FRED API key not configured" instead of charts.

### Sentiment

**AAII** (weekly): Scrape `https://www.aaii.com/sentimentsurvey/sent_results` for Bullish%, Neutral%, Bearish%. CSV import fallback via `POST /api/market/sentiment/import`.

**NAAIM** (weekly): Scrape `https://www.naaim.org/programs/naaim-exposure-index/` for exposure number (0-200 scale). Same CSV fallback.

Both scrapers log warnings on failure and continue — no exceptions propagated.

---

## 3. Database

### New Tables (Alembic migration 006)

```sql
CREATE TABLE macro_series (
    id          SERIAL PRIMARY KEY,
    series_id   VARCHAR(20) NOT NULL,
    date        DATE NOT NULL,
    value       NUMERIC(12, 4),
    UNIQUE(series_id, date)
);
CREATE INDEX idx_macro_series_lookup ON macro_series(series_id, date DESC);

CREATE TABLE sentiment_data (
    id          SERIAL PRIMARY KEY,
    source      VARCHAR(20) NOT NULL,   -- "aaii" | "naaim"
    week_ending DATE NOT NULL,
    value       NUMERIC(8, 4) NOT NULL, -- bull_bear_spread for AAII, exposure for NAAIM
    extra       JSONB,                  -- {bullish_pct, neutral_pct, bearish_pct} for AAII
    UNIQUE(source, week_ending)
);

CREATE TABLE market_regime (
    id              SERIAL PRIMARY KEY,
    as_of_date      DATE NOT NULL UNIQUE,
    regime          VARCHAR(20) NOT NULL,
    breadth         VARCHAR(10) NOT NULL,
    momentum        VARCHAR(10) NOT NULL,
    sentiment       VARCHAR(15) NOT NULL,
    macro           VARCHAR(15) NOT NULL,
    summary         TEXT NOT NULL,
    scanner_implication TEXT NOT NULL
);
```

Market price data reuses existing `symbols` + `ohlcv` tables — no new tables needed. Market tickers are added to `symbols` with a `_market_indices` watchlist for grouping.

---

## 4. Module Structure

```
backend/app/market/
    __init__.py
    ingestion.py        # yfinance fetch for market tickers, FRED fetch orchestration
    fred_client.py      # Thin async FRED API wrapper
    sentiment.py        # AAII/NAAIM scrape + CSV parse
    indicators.py       # Breadth, momentum, macro, sentiment computation
    regime.py           # MarketRegime classification
```

### Models

New SQLAlchemy models in `backend/app/models/`:
- `macro_series.py` — `MacroSeries` model
- `sentiment_data.py` — `SentimentData` model
- `market_regime.py` — `MarketRegimeModel` model

### Schemas

New Pydantic schemas in `backend/app/schemas/market.py`:
- `MarketRegimeResponse` — regime + all sub-signals + summary
- `TimeSeriesResponse` — `{labels: list[str], series: list[{name: str, data: list[float | None]}]}`
- `SentimentImportResponse` — rows imported count
- `RefreshStatusResponse` — job status + timestamp

### API Router

`backend/app/api/market.py` — mounted at `/api/market`

---

## 5. FRED Client

```python
# backend/app/market/fred_client.py

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

async def fetch_fred_series(
    series_id: str,
    api_key: str,
    observation_start: str,
) -> pd.DataFrame:
    """Fetch a FRED series. Returns DataFrame with columns: date, value.
    Returns empty DataFrame if API key is missing or request fails."""
```

Uses `httpx.AsyncClient` for HTTP. Handles FRED's `"."` missing value marker by converting to `None`. Rate-limits to 1 request per second (FRED TOS).

---

## 6. Sentiment Scraping

```python
# backend/app/market/sentiment.py

@dataclass
class AAIISentiment:
    week_ending: date
    bullish_pct: float
    neutral_pct: float
    bearish_pct: float
    bull_bear_spread: float  # bullish - bearish

async def scrape_aaii() -> list[AAIISentiment]:
    """Scrape AAII sentiment survey. Returns empty list on failure."""

async def scrape_naaim() -> list[dict]:
    """Scrape NAAIM exposure index. Returns empty list on failure."""

def parse_aaii_csv(content: str) -> list[AAIISentiment]:
    """Parse uploaded AAII CSV. Expected columns: date, bullish, neutral, bearish."""

def parse_naaim_csv(content: str) -> list[dict]:
    """Parse uploaded NAAIM CSV. Expected columns: date, exposure."""
```

All scrapers wrapped in try/except — failures log warnings and return empty lists. No exceptions propagated to callers.

---

## 7. Computed Indicators

All functions are pure sync, operating on DataFrames/Series.

### Breadth (`compute_breadth`)

- **SPX/RSP ratio**: `spx_close / rsp_close`, with 20-day and 50-day MAs
- **Signal**: `"broad"` if RSP outperforming over 20d, `"narrow"` if SPX outperforming, `"neutral"` if flat
- **Mag 7 index**: Equal-weight of 7 components, each normalized to 100 at series start. RSI(14) computed on the index. Divergence from SPX = concentration risk signal

### Momentum (`compute_momentum`)

- **SPX RSI(14)**: Overbought (>70) / oversold (<30) context
- **QQQ RSI(14)**: Tech sector momentum
- **VIX level**: <15 complacent, 15-25 normal, >25 elevated fear
- **VIX 20-day trend**: Rising = increasing uncertainty

### Macro (`compute_macro`)

- **Yield curve spread**: 10Y - 2Y. Positive = `"normal"`, negative = `"inverted"`. Track current spread + 30-day change + inversion duration in days
- **DXY RSI(14) + trend**: Strong USD = headwind for risk assets
- **M2 YoY% change**: Contracting M2 = liquidity headwind
- Returns empty/neutral results if FRED data unavailable

### Sentiment (`compute_sentiment`)

- **AAII bull-bear spread**: >+20 contrarian bearish, <-20 contrarian bullish. 4-week MA to smooth
- **NAAIM exposure**: >90 limited buying power, <40 defensive positioning (fuel for rally)

---

## 8. Market Regime Classification

```python
@dataclass
class MarketRegime:
    as_of_date: date
    regime: str              # "bull_trending" | "bull_extended" | "choppy" | "bear_warning" | "bear"
    breadth: str             # "broad" | "narrow" | "neutral"
    momentum: str            # "strong" | "moderate" | "weak" | "oversold"
    sentiment: str           # "fearful" | "neutral" | "complacent" | "euphoric"
    macro: str               # "supportive" | "neutral" | "headwind"
    summary: str             # 1-2 sentence plain-English description
    scanner_implication: str  # e.g. "Favorable for momentum setups"
```

**Regime rules** (simple, rule-based):

| Regime | Conditions |
|--------|-----------|
| `bull_trending` | SPX > 200 EMA, RSI 50-70, broad breadth, yield curve not deeply inverted |
| `bull_extended` | SPX > 200 EMA, RSI >70, narrow breadth, AAII spread >+20 |
| `choppy` | SPX within ±3% of 200 EMA, OR VIX >20 + conflicting signals |
| `bear_warning` | SPX < 200 EMA OR yield curve inverted >3 months + narrowing breadth |
| `bear` | SPX < 200 EMA, RSI <45, VIX >25, NAAIM <50 |

**Scanner implications per regime:**
- `bull_trending` → "Favorable for momentum and trend-following setups"
- `bull_extended` → "Consider tightening stops, extended conditions"
- `choppy` → "Favor mean reversion, reduce position sizes"
- `bear_warning` → "Defensive positioning, favor cash and hedges"
- `bear` → "Reduce exposure, look for oversold bounces only"

---

## 9. Scheduler Job

Added to `backend/app/scheduler.py`:

```python
scheduler.add_job(
    run_market_data_refresh,
    CronTrigger(hour=17, minute=0, timezone="America/New_York"),
    id="market_data_nightly",
    replace_existing=True,
)
```

Runs at 5:00 PM ET (after market close, before existing 6:00 AM nightly jobs next day).

**Job sequence:**
1. Ensure `_market_indices` watchlist + symbols exist (idempotent)
2. Fetch yfinance OHLCV for all market tickers (incremental)
3. Fetch FRED series (if key configured)
4. Attempt AAII/NAAIM scrape (log warning on failure)
5. Compute all indicators from fetched data
6. Compute and store MarketRegime
7. Prune `market_regime` rows older than 90 days

---

## 10. API Endpoints

Router: `backend/app/api/market.py`, prefix `/api/market`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/regime` | Current MarketRegime |
| GET | `/breadth` | SPX/RSP ratio + Mag7 data (last 252 bars) |
| GET | `/momentum` | SPX/QQQ RSI + VIX (last 252 bars) |
| GET | `/macro` | Yield curve + DXY + M2 (last 252 bars) |
| GET | `/sentiment` | AAII + NAAIM history (last 52 weeks) |
| POST | `/sentiment/import` | CSV upload for AAII or NAAIM data |
| POST | `/refresh` | Trigger manual data refresh |

Time series endpoints return:
```json
{
  "labels": ["2025-01-02", "2025-01-03", ...],
  "series": [
    {"name": "spx_rsp_ratio", "data": [1.02, 1.03, ...]},
    {"name": "ratio_ma20", "data": [1.01, 1.02, ...]}
  ]
}
```

---

## 11. Frontend

### Route & Navigation

New route `/market` → `MarketPage.tsx`. Nav link added alongside Scanner, Watchlists, Backtest.

### Components

**`MarketRegimeBanner.tsx`** — Large colored header card:
- Regime label with color (green = bull, yellow = choppy, red = bear)
- Sub-signal pills (breadth, momentum, sentiment, macro)
- `scanner_implication` text
- "Last updated" timestamp

**`MarketRegimeStrip.tsx`** — Compact one-liner for scanner page:
- Format: "Bull Trending — Favorable for momentum setups"
- Color-coded dot, links to `/market`
- Fetches regime from `/api/market/regime`

**`BreadthPanel.tsx`**:
- SPX/RSP ratio line chart (1 year) with 20/50-day MAs
- Mag7 equal-weight index vs SPX (normalized, dual line)
- Stats: current ratio, trend direction, breadth signal

**`MomentumPanel.tsx`**:
- SPX price chart (TradingView Lightweight Charts, 252 bars) with RSI pane
- VIX line chart with 15/25 horizontal reference lines
- Stats: SPX RSI, QQQ RSI, VIX level + 20d change

**`MacroPanel.tsx`**:
- Yield curve spread line chart, zero reference, red fill when inverted
- DXY line chart with RSI
- M2 YoY% bar chart
- Stats: current spread, inversion duration, DXY trend
- Shows "FRED API key not configured" if no macro data

**`SentimentPanel.tsx`**:
- AAII bull-bear spread bar chart (52 weeks), ±20 reference lines
- NAAIM exposure line chart, 40/90 reference lines
- Stats: latest AAII spread, 4-week MA, NAAIM reading
- Manual import button for CSV fallback

### State Management

- TanStack Query for all API calls (regime, breadth, momentum, macro, sentiment)
- No Zustand store needed — this page is read-only with no complex client state

---

## 12. Scanner Page Integration

Add `<MarketRegimeStrip />` at the top of `ScannerPage.tsx`, above the profile tabs. Read-only contextual callout — does not filter or modify scanner behavior.

---

## 13. Config Changes

Add to `backend/app/config.py`:
```python
fred_api_key: str | None = None
```

Add to `.env.example`:
```
FRED_API_KEY=  # Free key from https://fred.stlouisfed.org/docs/api/api_key.html
```

---

## 14. Testing

### `test_market_indicators.py`
- Breadth ratio computed correctly from synthetic SPX/RSP close arrays
- Mag7 equal-weight index normalizes to 100 at start
- Yield curve spread = 10Y - 2Y, sign correct for normal/inverted
- MarketRegime classification: one test per regime with synthetic indicator values
- Regime with missing FRED data still produces a valid classification (degrades gracefully)

### `test_fred_client.py`
- Mock httpx response, verify DataFrame columns and types
- Missing values (`"."`) converted to None
- Missing API key returns empty DataFrame (no exception)
- HTTP error returns empty DataFrame with warning logged

### `test_sentiment.py`
- CSV import parses correctly for both AAII and NAAIM formats
- Malformed CSV raises/handles gracefully
- Scrape function returns empty list on connection error (mocked)

All tests use synthetic data and mocked HTTP — no live API calls.

---

## 15. Out of Scope

- Feeding regime into per-stock composite scoring
- Sector rotation analysis
- International markets
- Options flow / put-call ratio
- Real-time intraday updates
