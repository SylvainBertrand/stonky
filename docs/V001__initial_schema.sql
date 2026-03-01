-- Stonky — Initial Database Schema
-- PostgreSQL 16 + TimescaleDB
-- Migration: V001__initial_schema.sql
--
-- Design principles:
--   1. TimescaleDB hypertables for time-series data (OHLCV, indicator cache)
--   2. Regular tables for config/metadata
--   3. JSONB for flexible config (indicator params, weights, signal details)
--   4. Composite indexes for the hot query paths (symbol+timeframe+time)
--   5. ENUMs for controlled vocabularies

-- ============================================================================
-- Extensions
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- ENUMs
-- ============================================================================

CREATE TYPE timeframe AS ENUM (
    '1m', '5m', '15m', '30m',
    '1h', '4h',
    '1d', '1w', '1M'
);

CREATE TYPE signal_direction AS ENUM ('bullish', 'bearish', 'neutral');

CREATE TYPE signal_category AS ENUM (
    'trend', 'momentum', 'volatility', 'volume',
    'support_resistance', 'divergence', 'pattern'
);

CREATE TYPE pattern_type AS ENUM (
    'harmonic', 'candlestick', 'chart_geometric'
);

CREATE TYPE scan_run_status AS ENUM (
    'pending', 'running', 'completed', 'failed'
);

-- ============================================================================
-- 1. SYMBOLS — Master symbol registry
-- ============================================================================
-- Single source of truth for all tracked instruments.
-- SA ratings live in sa_ratings table (separate refresh cadence, history tracking).

CREATE TABLE symbols (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(20) NOT NULL UNIQUE,
    name            VARCHAR(255),
    exchange        VARCHAR(20),         -- NYSE, NASDAQ, etc.
    asset_type      VARCHAR(20) NOT NULL DEFAULT 'stock',  -- stock, etf, crypto
    sector          VARCHAR(100),
    industry        VARCHAR(100),
    -- Housekeeping
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_symbols_ticker ON symbols(ticker);
CREATE INDEX idx_symbols_asset_type ON symbols(asset_type);
CREATE INDEX idx_symbols_active ON symbols(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- 1b. SA RATINGS — SeekingAlpha Quant/Analyst data (from spreadsheet import)
-- ============================================================================
-- One row per symbol per snapshot. Keeping history lets us track rating changes.
-- Source: SeekingAlpha Quant spreadsheet export (Summary + Ratings + Dividends sheets).
--
-- Letter grades stored as VARCHAR(3): A+, A, A-, B+, B, B-, C+, C, C-, D+, D, D-, F
-- Scores stored as NUMERIC(4,2): 1.00–5.00 scale

CREATE TYPE sa_letter_grade AS ENUM (
    'A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D', 'D-', 'F'
);

CREATE TABLE sa_ratings (
    id              SERIAL PRIMARY KEY,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    snapshot_date   DATE NOT NULL,       -- when this data was exported from SA

    -- === Summary sheet: Three headline scores (numeric 1.00-5.00) ===
    quant_score         NUMERIC(4,2),    -- e.g. 3.48
    sa_analyst_score    NUMERIC(4,2),    -- e.g. 3.28
    wall_st_score       NUMERIC(4,2),    -- e.g. 4.06

    -- === Ratings sheet: Quant factor grades ===
    valuation_grade     sa_letter_grade,
    growth_grade        sa_letter_grade,
    profitability_grade sa_letter_grade,
    momentum_grade      sa_letter_grade,
    eps_revision_grade  sa_letter_grade,

    -- === Dividends sheet: Dividend grades ===
    div_safety_grade    sa_letter_grade,
    div_growth_grade    sa_letter_grade,
    div_yield_grade     sa_letter_grade,
    div_consistency_grade sa_letter_grade,

    -- === Dividends sheet: Key dividend metrics ===
    yield_fwd           NUMERIC(8,6),    -- forward yield as decimal (0.0039 = 0.39%)
    payout_ratio        NUMERIC(8,6),    -- as decimal (0.13 = 13%)
    div_growth_3y       NUMERIC(8,6),    -- 3-year CAGR as decimal
    div_growth_5y       NUMERIC(8,6),    -- 5-year CAGR as decimal
    years_of_growth     INTEGER,         -- consecutive years of dividend growth
    div_frequency       VARCHAR(20),     -- Quarterly, Monthly, Annual, Semi-Annual

    -- === Risk (from Dividends sheet) ===
    beta_24m            NUMERIC(8,6),    -- 24-month beta

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(symbol_id, snapshot_date)
);

-- Hot path: "get latest ratings for all symbols in a watchlist"
CREATE INDEX idx_sa_ratings_symbol_date ON sa_ratings(symbol_id, snapshot_date DESC);
-- Filter path: "all stocks with momentum grade >= B"
CREATE INDEX idx_sa_ratings_momentum ON sa_ratings(momentum_grade, snapshot_date DESC);

-- ============================================================================
-- 2. WATCHLISTS — User-curated lists
-- ============================================================================

CREATE TABLE watchlists (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL UNIQUE,
    description     TEXT,
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE watchlist_items (
    id              SERIAL PRIMARY KEY,
    watchlist_id    INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes           TEXT,
    UNIQUE(watchlist_id, symbol_id)
);

CREATE INDEX idx_watchlist_items_watchlist ON watchlist_items(watchlist_id);

-- ============================================================================
-- 3. OHLCV — Price data hypertable
-- ============================================================================
-- TimescaleDB hypertable partitioned by time.
-- One row per symbol per timeframe per bar.

CREATE TABLE ohlcv (
    time            TIMESTAMPTZ NOT NULL,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    timeframe       timeframe NOT NULL,
    open            NUMERIC(20,8) NOT NULL,
    high            NUMERIC(20,8) NOT NULL,
    low             NUMERIC(20,8) NOT NULL,
    close           NUMERIC(20,8) NOT NULL,
    volume          BIGINT NOT NULL DEFAULT 0,
    -- For adjusted prices (splits, dividends)
    adj_close       NUMERIC(20,8),
    UNIQUE(time, symbol_id, timeframe)
);

SELECT create_hypertable('ohlcv', 'time');

-- Hot path: "give me daily bars for AAPL"
CREATE INDEX idx_ohlcv_symbol_tf_time ON ohlcv(symbol_id, timeframe, time DESC);

-- ============================================================================
-- 4. INDICATOR CACHE — Precomputed indicator values
-- ============================================================================
-- Avoids recalculating EMA/RSI/etc. on every scan run.
-- JSONB value column holds the indicator output (scalar, array, or struct).
-- Keyed by (time, symbol, timeframe, indicator_name, params_hash).

CREATE TABLE indicator_cache (
    time            TIMESTAMPTZ NOT NULL,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    timeframe       timeframe NOT NULL,
    indicator_name  VARCHAR(50) NOT NULL,   -- 'ema_21', 'rsi_14', 'macd_12_26_9', etc.
    params_hash     VARCHAR(32) NOT NULL,   -- MD5 of params JSON for uniqueness
    value           JSONB NOT NULL,         -- flexible: {"value": 65.3} or {"upper": 150.2, "middle": 145.0, "lower": 139.8}
    UNIQUE(time, symbol_id, timeframe, indicator_name, params_hash)
);

SELECT create_hypertable('indicator_cache', 'time');

CREATE INDEX idx_indicator_cache_lookup
    ON indicator_cache(symbol_id, timeframe, indicator_name, time DESC);

-- ============================================================================
-- 5. SCAN PROFILES — Configurable scan templates
-- ============================================================================
-- Each profile defines: which indicators to run, their parameters,
-- the category weights for scoring, and any hard filter conditions.

CREATE TABLE scan_profiles (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL UNIQUE,  -- 'Momentum Breakout', 'Mean Reversion', etc.
    description     TEXT,
    -- Indicator configuration: list of indicators with params
    -- Example: [{"name": "rsi", "params": {"period": 14}, "category": "momentum"}, ...]
    indicators      JSONB NOT NULL DEFAULT '[]',
    -- Category weights for composite scoring (must sum to 1.0)
    -- Example: {"trend": 0.30, "momentum": 0.20, "volume": 0.15, ...}
    category_weights JSONB NOT NULL DEFAULT '{}',
    -- Hard filter conditions (all must pass for a stock to be scored)
    -- Example: {"min_categories_agreeing": 3, "trend_must_agree": true, "volume_must_not_contradict": true}
    filters         JSONB NOT NULL DEFAULT '{}',
    -- Timeframes this profile operates on
    -- Example: {"primary": "1d", "confirmation": "1w"}
    timeframes      JSONB NOT NULL DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 6. SCAN RUNS — Execution log
-- ============================================================================
-- One row per scan execution. Links a profile to a watchlist at a point in time.

CREATE TABLE scan_runs (
    id              SERIAL PRIMARY KEY,
    profile_id      INTEGER NOT NULL REFERENCES scan_profiles(id) ON DELETE CASCADE,
    watchlist_id    INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    status          scan_run_status NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT,
    -- Summary stats
    symbols_scanned INTEGER DEFAULT 0,
    symbols_scored  INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scan_runs_profile ON scan_runs(profile_id, created_at DESC);
CREATE INDEX idx_scan_runs_status ON scan_runs(status) WHERE status IN ('pending', 'running');

-- ============================================================================
-- 7. SCAN RESULTS — Per-stock composite scores
-- ============================================================================
-- One row per stock per scan run. The ranked output.

CREATE TABLE scan_results (
    id              SERIAL PRIMARY KEY,
    scan_run_id     INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    -- Composite score: -1.0 (max bearish) to +1.0 (max bullish)
    composite_score NUMERIC(5,4) NOT NULL,
    direction       signal_direction NOT NULL,
    -- Category sub-scores
    -- Example: {"trend": 0.8, "momentum": 0.5, "volume": 0.3, ...}
    category_scores JSONB NOT NULL DEFAULT '{}',
    -- Which profiles this stock matched (could match multiple)
    profile_matches JSONB NOT NULL DEFAULT '[]',
    -- Risk/reward derived from ATR, Fib levels, pattern PRZ
    -- Example: {"entry": 150.25, "stop": 146.80, "target_1": 158.50, "target_2": 165.00, "risk_reward_ratio": 2.4}
    risk_reward     JSONB,
    -- Number of agreeing categories
    categories_agreeing INTEGER NOT NULL DEFAULT 0,
    -- Rank within this scan run (1 = highest score)
    rank            INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(scan_run_id, symbol_id)
);

CREATE INDEX idx_scan_results_run_rank ON scan_results(scan_run_id, rank);
CREATE INDEX idx_scan_results_symbol ON scan_results(symbol_id, created_at DESC);

-- ============================================================================
-- 8. SIGNAL RESULTS — Individual indicator signals per stock per run
-- ============================================================================
-- Granular: one row per indicator signal per stock per scan run.
-- Feeds the scoring engine and enables drill-down in the UI.

CREATE TABLE signal_results (
    id              SERIAL PRIMARY KEY,
    scan_run_id     INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    indicator_name  VARCHAR(50) NOT NULL,
    category        signal_category NOT NULL,
    -- Normalized signal: -1.0 to +1.0
    signal_value    NUMERIC(5,4) NOT NULL,
    direction       signal_direction NOT NULL,
    -- Raw indicator output for display/debugging
    -- Example for RSI: {"rsi": 28.5, "zone": "oversold"}
    -- Example for MACD: {"macd": 1.23, "signal": 0.98, "histogram": 0.25, "crossover": "bullish"}
    raw_values      JSONB NOT NULL DEFAULT '{}',
    -- Human-readable signal description for UI tooltip
    signal_label    VARCHAR(255),        -- e.g. "RSI oversold (28.5)", "Bullish MACD crossover"
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_signal_results_run_symbol
    ON signal_results(scan_run_id, symbol_id);
CREATE INDEX idx_signal_results_category
    ON signal_results(scan_run_id, category);

-- ============================================================================
-- 9. PATTERN DETECTIONS — Harmonic, candlestick, chart patterns
-- ============================================================================
-- Separate from signal_results because patterns have richer structure
-- (XABCD points, PRZ zones, visual annotations).

CREATE TABLE pattern_detections (
    id              SERIAL PRIMARY KEY,
    scan_run_id     INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    timeframe       timeframe NOT NULL,
    pattern_type    pattern_type NOT NULL,
    pattern_name    VARCHAR(50) NOT NULL,  -- 'gartley', 'bullish_engulfing', 'double_top', etc.
    direction       signal_direction NOT NULL,
    -- Confidence: 0.0 to 1.0 (how closely ratios match ideal, pattern quality)
    confidence      NUMERIC(4,3) NOT NULL,
    -- Pattern geometry — flexible per type
    -- Harmonic example: {"X": {"time": "...", "price": 145.0}, "A": {...}, "B": {...}, "C": {...}, "D": {...},
    --                     "ratios": {"XA_ret": 0.618, "AB_ret": 0.886}, "prz": {"low": 142.5, "high": 144.0}}
    -- Candlestick example: {"candles": [{"time": "...", "o": 150, "h": 152, "l": 148, "c": 151}], "context": "at_support"}
    -- Chart geometric example: {"points": [...], "neckline": 145.0, "target": 155.0}
    geometry        JSONB NOT NULL DEFAULT '{}',
    -- When the pattern was detected (the bar at which it completed)
    detected_at     TIMESTAMPTZ NOT NULL,
    -- Invalidation level (price beyond which pattern is void)
    invalidation    NUMERIC(20,8),
    -- Target levels derived from pattern
    targets         JSONB,               -- {"t1": 155.0, "t2": 162.0}
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pattern_detections_run_symbol
    ON pattern_detections(scan_run_id, symbol_id);
CREATE INDEX idx_pattern_detections_type
    ON pattern_detections(pattern_type, pattern_name);
CREATE INDEX idx_pattern_detections_detected
    ON pattern_detections(detected_at DESC);

-- ============================================================================
-- 10. DIVERGENCES — Detected divergences
-- ============================================================================
-- Could be in signal_results, but divergences have specific structure
-- (two pivot pairs) that benefits from dedicated columns.

CREATE TABLE divergences (
    id              SERIAL PRIMARY KEY,
    scan_run_id     INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    timeframe       timeframe NOT NULL,
    indicator_name  VARCHAR(50) NOT NULL,  -- 'rsi', 'macd_histogram', 'obv'
    divergence_type VARCHAR(20) NOT NULL,  -- 'regular_bullish', 'regular_bearish', 'hidden_bullish', 'hidden_bearish'
    direction       signal_direction NOT NULL,
    -- The two pivot pairs that form the divergence
    -- Example: {"price_pivot_1": {"time": "...", "value": 145.0}, "price_pivot_2": {"time": "...", "value": 142.0},
    --           "indicator_pivot_1": {"time": "...", "value": 32.0}, "indicator_pivot_2": {"time": "...", "value": 38.0}}
    pivots          JSONB NOT NULL,
    confidence      NUMERIC(4,3) NOT NULL, -- based on pivot clarity and time span
    detected_at     TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_divergences_run_symbol
    ON divergences(scan_run_id, symbol_id);

-- ============================================================================
-- 11. SWING POINTS — Detected swing highs/lows
-- ============================================================================
-- Shared infrastructure: feeds Fibonacci retracement, divergence detection,
-- anchored VWAP, and horizontal S/R clustering.
-- Precomputed and cached per symbol/timeframe.

CREATE TABLE swing_points (
    id              SERIAL PRIMARY KEY,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    timeframe       timeframe NOT NULL,
    time            TIMESTAMPTZ NOT NULL,
    type            VARCHAR(10) NOT NULL,  -- 'high' or 'low'
    price           NUMERIC(20,8) NOT NULL,
    -- Strength: how many bars on each side confirm this pivot
    strength        INTEGER NOT NULL DEFAULT 5,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(symbol_id, timeframe, time, type)
);

CREATE INDEX idx_swing_points_lookup
    ON swing_points(symbol_id, timeframe, time DESC);

-- ============================================================================
-- 12. DATA INGESTION LOG — Track fetch history
-- ============================================================================

CREATE TABLE ingestion_log (
    id              SERIAL PRIMARY KEY,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    timeframe       timeframe NOT NULL,
    source          VARCHAR(50) NOT NULL,  -- 'yfinance', 'alpha_vantage', 'polygon', 'ccxt'
    bars_fetched    INTEGER NOT NULL DEFAULT 0,
    latest_bar      TIMESTAMPTZ,
    status          VARCHAR(20) NOT NULL DEFAULT 'success',  -- 'success', 'error', 'partial'
    error_message   TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ingestion_log_symbol
    ON ingestion_log(symbol_id, timeframe, fetched_at DESC);

-- ============================================================================
-- Trigger: auto-update updated_at timestamps
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_symbols_updated_at
    BEFORE UPDATE ON symbols FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_watchlists_updated_at
    BEFORE UPDATE ON watchlists FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_scan_profiles_updated_at
    BEFORE UPDATE ON scan_profiles FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- TimescaleDB retention & compression policies (tune later)
-- ============================================================================
-- Compress OHLCV chunks older than 30 days
-- ALTER TABLE ohlcv SET (timescaledb.compress,
--     timescaledb.compress_segmentby = 'symbol_id,timeframe');
-- SELECT add_compression_policy('ohlcv', INTERVAL '30 days');

-- Compress indicator cache older than 7 days
-- ALTER TABLE indicator_cache SET (timescaledb.compress,
--     timescaledb.compress_segmentby = 'symbol_id,timeframe,indicator_name');
-- SELECT add_compression_policy('indicator_cache', INTERVAL '7 days');

-- Retention: drop indicator cache older than 90 days (regenerable)
-- SELECT add_retention_policy('indicator_cache', INTERVAL '90 days');
