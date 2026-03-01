"""Initial schema — all tables, ENUMs, hypertables, indexes, triggers.

Revision ID: 001
Revises: None
Create Date: 2026-02-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # Extensions
    # =========================================================================
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # =========================================================================
    # ENUMs
    # =========================================================================
    op.execute("""
        CREATE TYPE timeframe AS ENUM (
            '1m', '5m', '15m', '30m',
            '1h', '4h',
            '1d', '1w', '1M'
        )
    """)

    op.execute("""
        CREATE TYPE signal_direction AS ENUM ('bullish', 'bearish', 'neutral')
    """)

    op.execute("""
        CREATE TYPE signal_category AS ENUM (
            'trend', 'momentum', 'volatility', 'volume',
            'support_resistance', 'divergence', 'pattern'
        )
    """)

    op.execute("""
        CREATE TYPE pattern_type AS ENUM (
            'harmonic', 'candlestick', 'chart_geometric'
        )
    """)

    op.execute("""
        CREATE TYPE scan_run_status AS ENUM (
            'pending', 'running', 'completed', 'failed'
        )
    """)

    op.execute("""
        CREATE TYPE sa_letter_grade AS ENUM (
            'A+', 'A', 'A-', 'B+', 'B', 'B-',
            'C+', 'C', 'C-', 'D+', 'D', 'D-', 'F'
        )
    """)

    # =========================================================================
    # 1. symbols
    # =========================================================================
    op.execute("""
        CREATE TABLE symbols (
            id          SERIAL PRIMARY KEY,
            ticker      VARCHAR(20) NOT NULL UNIQUE,
            name        VARCHAR(255),
            exchange    VARCHAR(20),
            asset_type  VARCHAR(20) NOT NULL DEFAULT 'stock',
            sector      VARCHAR(100),
            industry    VARCHAR(100),
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_symbols_ticker ON symbols(ticker)")
    op.execute("CREATE INDEX idx_symbols_asset_type ON symbols(asset_type)")
    op.execute(
        "CREATE INDEX idx_symbols_active ON symbols(is_active) WHERE is_active = TRUE"
    )

    # =========================================================================
    # 1b. sa_ratings
    # =========================================================================
    op.execute("""
        CREATE TABLE sa_ratings (
            id                      SERIAL PRIMARY KEY,
            symbol_id               INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            snapshot_date           DATE NOT NULL,
            quant_score             NUMERIC(4,2),
            sa_analyst_score        NUMERIC(4,2),
            wall_st_score           NUMERIC(4,2),
            valuation_grade         sa_letter_grade,
            growth_grade            sa_letter_grade,
            profitability_grade     sa_letter_grade,
            momentum_grade          sa_letter_grade,
            eps_revision_grade      sa_letter_grade,
            div_safety_grade        sa_letter_grade,
            div_growth_grade        sa_letter_grade,
            div_yield_grade         sa_letter_grade,
            div_consistency_grade   sa_letter_grade,
            yield_fwd               NUMERIC(8,6),
            payout_ratio            NUMERIC(8,6),
            div_growth_3y           NUMERIC(8,6),
            div_growth_5y           NUMERIC(8,6),
            years_of_growth         INTEGER,
            div_frequency           VARCHAR(20),
            beta_24m                NUMERIC(8,6),
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(symbol_id, snapshot_date)
        )
    """)
    op.execute(
        "CREATE INDEX idx_sa_ratings_symbol_date ON sa_ratings(symbol_id, snapshot_date DESC)"
    )
    op.execute(
        "CREATE INDEX idx_sa_ratings_momentum ON sa_ratings(momentum_grade, snapshot_date DESC)"
    )

    # =========================================================================
    # 2. watchlists
    # =========================================================================
    op.execute("""
        CREATE TABLE watchlists (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(100) NOT NULL UNIQUE,
            description TEXT,
            is_default  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE watchlist_items (
            id           SERIAL PRIMARY KEY,
            watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
            symbol_id    INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            added_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes        TEXT,
            UNIQUE(watchlist_id, symbol_id)
        )
    """)
    op.execute(
        "CREATE INDEX idx_watchlist_items_watchlist ON watchlist_items(watchlist_id)"
    )

    # =========================================================================
    # 3. ohlcv (hypertable)
    # =========================================================================
    op.execute("""
        CREATE TABLE ohlcv (
            time        TIMESTAMPTZ NOT NULL,
            symbol_id   INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            timeframe   timeframe NOT NULL,
            open        NUMERIC(20,8) NOT NULL,
            high        NUMERIC(20,8) NOT NULL,
            low         NUMERIC(20,8) NOT NULL,
            close       NUMERIC(20,8) NOT NULL,
            volume      BIGINT NOT NULL DEFAULT 0,
            adj_close   NUMERIC(20,8),
            UNIQUE(time, symbol_id, timeframe)
        )
    """)
    op.execute("SELECT create_hypertable('ohlcv', 'time')")
    op.execute(
        "CREATE INDEX idx_ohlcv_symbol_tf_time ON ohlcv(symbol_id, timeframe, time DESC)"
    )

    # =========================================================================
    # 4. indicator_cache (hypertable)
    # =========================================================================
    op.execute("""
        CREATE TABLE indicator_cache (
            time            TIMESTAMPTZ NOT NULL,
            symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            timeframe       timeframe NOT NULL,
            indicator_name  VARCHAR(50) NOT NULL,
            params_hash     VARCHAR(32) NOT NULL,
            value           JSONB NOT NULL,
            UNIQUE(time, symbol_id, timeframe, indicator_name, params_hash)
        )
    """)
    op.execute("SELECT create_hypertable('indicator_cache', 'time')")
    op.execute("""
        CREATE INDEX idx_indicator_cache_lookup
            ON indicator_cache(symbol_id, timeframe, indicator_name, time DESC)
    """)

    # =========================================================================
    # 5. scan_profiles
    # =========================================================================
    op.execute("""
        CREATE TABLE scan_profiles (
            id               SERIAL PRIMARY KEY,
            name             VARCHAR(100) NOT NULL UNIQUE,
            description      TEXT,
            indicators       JSONB NOT NULL DEFAULT '[]',
            category_weights JSONB NOT NULL DEFAULT '{}',
            filters          JSONB NOT NULL DEFAULT '{}',
            timeframes       JSONB NOT NULL DEFAULT '{}',
            is_active        BOOLEAN NOT NULL DEFAULT TRUE,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # =========================================================================
    # 6. scan_runs
    # =========================================================================
    op.execute("""
        CREATE TABLE scan_runs (
            id              SERIAL PRIMARY KEY,
            profile_id      INTEGER NOT NULL REFERENCES scan_profiles(id) ON DELETE CASCADE,
            watchlist_id    INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
            status          scan_run_status NOT NULL DEFAULT 'pending',
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            error_message   TEXT,
            symbols_scanned INTEGER DEFAULT 0,
            symbols_scored  INTEGER DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX idx_scan_runs_profile ON scan_runs(profile_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_scan_runs_status ON scan_runs(status)"
        " WHERE status IN ('pending', 'running')"
    )

    # =========================================================================
    # 7. scan_results
    # =========================================================================
    op.execute("""
        CREATE TABLE scan_results (
            id                  SERIAL PRIMARY KEY,
            scan_run_id         INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
            symbol_id           INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            composite_score     NUMERIC(5,4) NOT NULL,
            direction           signal_direction NOT NULL,
            category_scores     JSONB NOT NULL DEFAULT '{}',
            profile_matches     JSONB NOT NULL DEFAULT '[]',
            risk_reward         JSONB,
            categories_agreeing INTEGER NOT NULL DEFAULT 0,
            rank                INTEGER,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(scan_run_id, symbol_id)
        )
    """)
    op.execute(
        "CREATE INDEX idx_scan_results_run_rank ON scan_results(scan_run_id, rank)"
    )
    op.execute(
        "CREATE INDEX idx_scan_results_symbol ON scan_results(symbol_id, created_at DESC)"
    )

    # =========================================================================
    # 8. signal_results
    # =========================================================================
    op.execute("""
        CREATE TABLE signal_results (
            id              SERIAL PRIMARY KEY,
            scan_run_id     INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
            symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            indicator_name  VARCHAR(50) NOT NULL,
            category        signal_category NOT NULL,
            signal_value    NUMERIC(5,4) NOT NULL,
            direction       signal_direction NOT NULL,
            raw_values      JSONB NOT NULL DEFAULT '{}',
            signal_label    VARCHAR(255),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX idx_signal_results_run_symbol ON signal_results(scan_run_id, symbol_id)"
    )
    op.execute(
        "CREATE INDEX idx_signal_results_category ON signal_results(scan_run_id, category)"
    )

    # =========================================================================
    # 9. pattern_detections
    # =========================================================================
    op.execute("""
        CREATE TABLE pattern_detections (
            id           SERIAL PRIMARY KEY,
            scan_run_id  INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
            symbol_id    INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            timeframe    timeframe NOT NULL,
            pattern_type pattern_type NOT NULL,
            pattern_name VARCHAR(50) NOT NULL,
            direction    signal_direction NOT NULL,
            confidence   NUMERIC(4,3) NOT NULL,
            geometry     JSONB NOT NULL DEFAULT '{}',
            detected_at  TIMESTAMPTZ NOT NULL,
            invalidation NUMERIC(20,8),
            targets      JSONB,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX idx_pattern_detections_run_symbol
            ON pattern_detections(scan_run_id, symbol_id)
    """)
    op.execute("""
        CREATE INDEX idx_pattern_detections_type
            ON pattern_detections(pattern_type, pattern_name)
    """)
    op.execute("""
        CREATE INDEX idx_pattern_detections_detected
            ON pattern_detections(detected_at DESC)
    """)

    # =========================================================================
    # 10. divergences
    # =========================================================================
    op.execute("""
        CREATE TABLE divergences (
            id              SERIAL PRIMARY KEY,
            scan_run_id     INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
            symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            timeframe       timeframe NOT NULL,
            indicator_name  VARCHAR(50) NOT NULL,
            divergence_type VARCHAR(20) NOT NULL,
            direction       signal_direction NOT NULL,
            pivots          JSONB NOT NULL,
            confidence      NUMERIC(4,3) NOT NULL,
            detected_at     TIMESTAMPTZ NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX idx_divergences_run_symbol ON divergences(scan_run_id, symbol_id)"
    )

    # =========================================================================
    # 11. swing_points
    # =========================================================================
    op.execute("""
        CREATE TABLE swing_points (
            id          SERIAL PRIMARY KEY,
            symbol_id   INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            timeframe   timeframe NOT NULL,
            time        TIMESTAMPTZ NOT NULL,
            type        VARCHAR(10) NOT NULL,
            price       NUMERIC(20,8) NOT NULL,
            strength    INTEGER NOT NULL DEFAULT 5,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(symbol_id, timeframe, time, type)
        )
    """)
    op.execute(
        "CREATE INDEX idx_swing_points_lookup ON swing_points(symbol_id, timeframe, time DESC)"
    )

    # =========================================================================
    # 12. ingestion_log
    # =========================================================================
    op.execute("""
        CREATE TABLE ingestion_log (
            id            SERIAL PRIMARY KEY,
            symbol_id     INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            timeframe     timeframe NOT NULL,
            source        VARCHAR(50) NOT NULL,
            bars_fetched  INTEGER NOT NULL DEFAULT 0,
            latest_bar    TIMESTAMPTZ,
            status        VARCHAR(20) NOT NULL DEFAULT 'success',
            error_message TEXT,
            fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX idx_ingestion_log_symbol
            ON ingestion_log(symbol_id, timeframe, fetched_at DESC)
    """)

    # =========================================================================
    # Trigger: auto-update updated_at
    # =========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_symbols_updated_at
            BEFORE UPDATE ON symbols FOR EACH ROW EXECUTE FUNCTION update_updated_at()
    """)
    op.execute("""
        CREATE TRIGGER trg_watchlists_updated_at
            BEFORE UPDATE ON watchlists FOR EACH ROW EXECUTE FUNCTION update_updated_at()
    """)
    op.execute("""
        CREATE TRIGGER trg_scan_profiles_updated_at
            BEFORE UPDATE ON scan_profiles FOR EACH ROW EXECUTE FUNCTION update_updated_at()
    """)


def downgrade() -> None:
    # Drop triggers first
    op.execute("DROP TRIGGER IF EXISTS trg_scan_profiles_updated_at ON scan_profiles")
    op.execute("DROP TRIGGER IF EXISTS trg_watchlists_updated_at ON watchlists")
    op.execute("DROP TRIGGER IF EXISTS trg_symbols_updated_at ON symbols")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at()")

    # Drop tables in reverse dependency order
    op.execute("DROP TABLE IF EXISTS ingestion_log")
    op.execute("DROP TABLE IF EXISTS swing_points")
    op.execute("DROP TABLE IF EXISTS divergences")
    op.execute("DROP TABLE IF EXISTS pattern_detections")
    op.execute("DROP TABLE IF EXISTS signal_results")
    op.execute("DROP TABLE IF EXISTS scan_results")
    op.execute("DROP TABLE IF EXISTS scan_runs")
    op.execute("DROP TABLE IF EXISTS scan_profiles")
    op.execute("DROP TABLE IF EXISTS indicator_cache")
    op.execute("DROP TABLE IF EXISTS ohlcv")
    op.execute("DROP TABLE IF EXISTS watchlist_items")
    op.execute("DROP TABLE IF EXISTS watchlists")
    op.execute("DROP TABLE IF EXISTS sa_ratings")
    op.execute("DROP TABLE IF EXISTS symbols")

    # Drop ENUMs
    op.execute("DROP TYPE IF EXISTS sa_letter_grade")
    op.execute("DROP TYPE IF EXISTS scan_run_status")
    op.execute("DROP TYPE IF EXISTS pattern_type")
    op.execute("DROP TYPE IF EXISTS signal_category")
    op.execute("DROP TYPE IF EXISTS signal_direction")
    op.execute("DROP TYPE IF EXISTS timeframe")
