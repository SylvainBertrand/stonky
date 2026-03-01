# Stonky

Personal investment analysis web app. Scanner-first architecture: run configurable TA pipelines on a curated watchlist, score and rank results, surface high-reward/low-risk setups.

## Tech Stack

- **Backend:** Python 3.12+, FastAPI, APScheduler/Celery, Alembic
- **Frontend:** React 18+, TypeScript, Vite, Zustand
- **Charting:** TradingView Lightweight Charts (upgrade path: Advanced Charts, Apache ECharts)
- **Database:** PostgreSQL 16 + TimescaleDB
- **Data sources:** yfinance, CCXT, Alpha Vantage/Polygon.io free tier, FRED
- **ML/TA:** pandas-ta, ta-lib, pyharmonics, scikit-learn, PyTorch

## Repo Structure

```
stonky/
├── CLAUDE.md
├── docker-compose.yml
├── backend/
│   ├── pyproject.toml          # uv/pip, dependencies
│   ├── alembic/                # DB migrations
│   ├── app/
│   │   ├── main.py             # FastAPI app factory
│   │   ├── config.py           # Pydantic settings
│   │   ├── models/             # SQLAlchemy models (mirrors DB schema)
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── api/                # FastAPI routers
│   │   │   ├── watchlists.py
│   │   │   ├── scanner.py
│   │   │   ├── symbols.py
│   │   │   └── ...
│   │   ├── services/           # Business logic
│   │   │   ├── ingestion.py    # Data fetching (yfinance, etc.)
│   │   │   ├── indicators.py   # TA indicator computation
│   │   │   ├── patterns.py     # Harmonic + candlestick detection
│   │   │   ├── divergence.py   # Divergence detection
│   │   │   ├── swing.py        # Swing point detection (shared infra)
│   │   │   ├── scoring.py      # Signal normalization + composite scoring
│   │   │   └── sa_import.py    # SeekingAlpha spreadsheet parser
│   │   ├── tasks/              # Background jobs (Celery/APScheduler)
│   │   └── db/                 # DB session, engine config
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── stores/             # Zustand stores
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── api/                # API client (typed, auto-generated from OpenAPI)
│   │   └── types/
│   └── tests/
└── docs/                       # Architecture docs, specs
    └── V001__initial_schema.sql
```

## Database

PostgreSQL 16 + TimescaleDB. 13 tables, 2 hypertables.

**Hypertables (time-series):**
- `ohlcv` — price bars, partitioned by time, keyed by (time, symbol_id, timeframe)
- `indicator_cache` — precomputed indicator values, JSONB output, 90-day retention

**Core tables:**
- `symbols` — master registry (ticker, exchange, sector, asset_type)
- `sa_ratings` — SeekingAlpha quant/analyst data with snapshot history (factor grades, dividend metrics, beta)
- `watchlists` / `watchlist_items` — M:N curated lists
- `scan_profiles` — indicator configs, category weights, filters as JSONB
- `scan_runs` — execution log
- `scan_results` — ranked composite scores per stock per run
- `signal_results` — individual indicator signals per stock per run
- `pattern_detections` — harmonic, candlestick, chart patterns with JSONB geometry
- `divergences` — RSI/MACD/OBV divergence with pivot pairs
- `swing_points` — shared infra: swing highs/lows feeding Fib, divergence, VWAP, S/R
- `ingestion_log` — data fetch tracking

Full DDL: `docs/V001__initial_schema.sql`

## Architecture Decisions

- **Scanner-first.** Build the per-stock scanner before backtesting, broad market, or rotation modules.
- **Layered TA pipeline:** rule-based detection (ElliottWaveAnalyzer, pyharmonics) → ML confidence scoring → LLM synthesis agent.
- **Scoring engine:** normalize every indicator to -1.0 to +1.0, aggregate by 7 weighted categories (trend 0.30, momentum 0.20, volume 0.15, volatility 0.10, S/R 0.10, divergence 0.10, pattern 0.05), composite score + profile filter.
- **Swing point detection** is shared infrastructure — used by Fibonacci retracement, divergence detection, anchored VWAP, and S/R clustering. Compute once, cache in `swing_points` table.
- **JSONB for flexibility** — indicator params, scan profile configs, pattern geometry, raw signal values. Adding a new indicator is a config change, not a schema migration.
- **SA ratings as separate table** — snapshot history to track rating changes over time.

## Coding Conventions

### Python (Backend)
- Use `uv` for dependency management if available, otherwise pip
- Type hints everywhere — `mypy --strict` compatible
- Pydantic v2 for all schemas and settings
- SQLAlchemy 2.0 style (mapped_column, declarative)
- Async where it matters (FastAPI routes, DB queries), sync for CPU-bound TA computation
- Tests with pytest, fixtures for DB sessions
- Ruff for linting and formatting

### TypeScript (Frontend)
- Strict mode
- Functional components only, hooks for state
- Zustand for global state (not Redux)
- TanStack Query for server state
- No `any` — prefer `unknown` + type guards

### General
- Commit messages: conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`)
- No premature abstraction — extract patterns after they repeat 3x
- Error handling: explicit, no silent catches
- Environment config via `.env` files, never hardcoded secrets

## Common Commands

```bash
# Backend
cd backend && uvicorn app.main:app --reload
cd backend && alembic upgrade head
cd backend && pytest

# Frontend
cd frontend && npm run dev
cd frontend && npm run build
cd frontend && npm test

# Docker
docker compose up -d                    # Start Postgres + TimescaleDB
docker compose down -v                  # Tear down with volumes
```

## What NOT to Do

- Don't use Django — we chose FastAPI for async + lightweight
- Don't use Redux — Zustand is the state manager
- Don't add InfluxDB — TimescaleDB is the time-series store
- Don't implement backtesting yet — it's P2
- Don't implement broad market analysis yet — it's P2/P3
- Don't use Parabolic SAR, Williams %R, CCI, or PPO — explicitly excluded as redundant (see TA survey)
- Don't store SA rating data on the symbols table — it lives in sa_ratings with snapshot history
- Don't hardcode indicator parameters — everything is configurable via scan_profiles JSONB
