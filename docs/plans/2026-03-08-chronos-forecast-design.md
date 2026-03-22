# Chronos-2 Forecasting Layer — Design

**Date:** 2026-03-08
**Milestone:** P1 — Time Series Forecasting Layer
**Model:** amazon/chronos-t5-small (Chronos-2 small, ~250MB)

## Overview

Probabilistic price forecasting context layer using Amazon Chronos-2. This is NOT a signal generator — it does not feed composite scoring. It provides directional context (bullish/bearish/neutral with confidence bands) visualized on the chart alongside existing TA signals.

Architecture follows the YOLO pattern: nightly background job → results cached in DB → read asynchronously by UI.

## Backend

### Forecaster Module (`backend/app/analysis/forecaster.py`)

- Singleton `ChronosPipeline` loaded lazily at module level (CPU-only, float32)
- Core function: `run_forecast(df, symbol, timeframe="1d", horizon=20, num_samples=50) → ForecastResult | None`
- Input: last 200 daily close prices (univariate)
- Output: `ForecastResult` dataclass with median, quantiles (10/25/75/90), direction, confidence, expected_move_pct
- Direction classification: >+2% = bullish, <-2% = bearish, else neutral
- Confidence: fraction of samples agreeing with direction
- Returns None if <50 bars available
- All inference wrapped in try/except — one symbol failure doesn't abort batch

### Database (`forecast_cache` table, migration 003)

```sql
CREATE TABLE forecast_cache (
    id              SERIAL PRIMARY KEY,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id),
    timeframe       VARCHAR(10) NOT NULL,
    generated_at    TIMESTAMPTZ NOT NULL,
    horizon_bars    INTEGER NOT NULL,
    last_bar_date   DATE NOT NULL,
    last_close      NUMERIC(12,4) NOT NULL,
    median          JSONB NOT NULL,
    quantile_10     JSONB NOT NULL,
    quantile_25     JSONB NOT NULL,
    quantile_75     JSONB NOT NULL,
    quantile_90     JSONB NOT NULL,
    direction       VARCHAR(10) NOT NULL,
    direction_confidence NUMERIC(5,4) NOT NULL,
    expected_move_pct    NUMERIC(7,4) NOT NULL
);
CREATE INDEX idx_forecast_cache_symbol_tf ON forecast_cache(symbol_id, timeframe, generated_at DESC);
```

- Retention: 7 days per symbol, purge older rows after each run
- Job tracking: reuse existing `scan_runs` table with marker `"chronos_forecast"`

### Scheduler (8:00 AM ET nightly)

- Added to `scheduler.py` as cron job after YOLO (6 AM) and EW (7 AM)
- `run_forecast_scan_all()` iterates active watchlist symbols sequentially (~2-5s per symbol on CPU)
- Creates `ScanRun` record for status tracking

### API (`backend/app/api/forecasts.py`)

- `GET /api/forecasts/{symbol}` — latest forecast for symbol
- `POST /api/forecasts/scan` — trigger manual forecast run
- `GET /api/forecasts/scan/status` — poll job status via scan_runs
- Router registered in `main.py`

## Frontend

### ForecastBanner (`components/stock/ForecastBanner.tsx`)

- Direction badge (green/red/gray), expected move %, confidence percentage
- Range display (10th–90th percentile)
- Placed below ElliottWaveBanner on StockDetailPage
- Shows "Not yet forecasted" if no data

### Chart Overlay (in `CandlestickChart.tsx`)

- Shaded band: q10–q90 at 0.08 alpha, colored by direction
- Inner band: q25–q75 at 0.15 alpha
- Dashed median line
- Label at end: "+4.2% (20d)"
- Starts at last bar + 1, extends rightward with synthetic future timestamps
- Behind `[Forecast]` toggle button (default off)

### Scanner Integration

- New "Forecast" column in ResultsTable: direction arrow + expected move %
- Only shown when direction_confidence > 0.6
- "Run Forecasts" button in scanner page header

## Testing

- `backend/tests/unit/test_forecaster.py` — mock Chronos pipeline, test direction classification, quantile computation, edge cases
- No regressions to existing tests

## Dependencies

- `chronos-forecasting` added to pyproject.toml
