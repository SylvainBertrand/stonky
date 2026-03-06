# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Stonky

Personal investment analysis web app. Scanner-first architecture: run configurable TA pipelines on a curated watchlist, score and rank results, surface high-reward/low-risk setups.

## Tech Stack

- **Backend:** Python 3.12+, FastAPI, APScheduler (3.x), Alembic
- **Frontend:** React 18+, TypeScript, Vite, Zustand, TanStack Query, React Router
- **Charting:** TradingView Lightweight Charts
- **Database:** PostgreSQL 16 + TimescaleDB
- **Data sources:** yfinance, openpyxl (SA import)
- **TA/ML:** pandas-ta, pyharmonics, scipy, ultralytics (YOLOv8), mplfinance, huggingface_hub

## Common Commands

```bash
# Backend
cd backend && uvicorn app.main:app --reload
cd backend && alembic upgrade head
cd backend && ruff check app/          # lint
cd backend && ruff format app/         # format
cd backend && mypy app/                # type check

# Backend tests
cd backend && pytest                                        # all tests
cd backend && pytest -m unit                               # fast, no containers
cd backend && pytest -m integration                        # needs Docker
cd backend && pytest -m ta_validation                      # golden file comparison
cd backend && pytest tests/unit/test_elliott_wave.py       # single file
cd backend && pytest tests/ta_validation/ --update-golden  # regenerate golden files

# Frontend
cd frontend && npm run dev
cd frontend && npm run build
cd frontend && npm test                # vitest
cd frontend && npm run test:coverage

# Docker (Postgres + TimescaleDB)
docker compose up -d
docker compose down -v
```

## Repo Structure

```
stonky/
├── CLAUDE.md
├── docker-compose.yml
├── .claude/agents/          # Sub-agents: frontend-sub-agent (haiku), test-writer (sonnet)
├── backend/
│   ├── pyproject.toml       # hatchling build; ta-lib in optional [ta] group (needs system install)
│   ├── alembic/             # DB migrations (versions/001_initial_schema.py, 002_nullable_scan_run_fks.py)
│   └── app/
│       ├── main.py          # FastAPI app factory + lifespan (scheduler start/stop)
│       ├── config.py        # Pydantic settings
│       ├── scheduler.py     # APScheduler jobs (nightly YOLO scan, data ingestion)
│       ├── analysis/        # Core TA pipeline (see below)
│       ├── api/             # FastAPI routers: health, watchlist, scanner, patterns, stocks
│       ├── ingestion/       # fetcher.py (yfinance), sa_import.py (SeekingAlpha xlsx)
│       ├── models/          # SQLAlchemy 2.0 models mirroring DB schema
│       ├── schemas/         # Pydantic v2 request/response schemas
│       ├── services/        # scoring.py (legacy; main scoring lives in analysis/)
│       ├── tasks/           # Background task stubs
│       └── db/session.py    # Async SQLAlchemy engine + AsyncSessionLocal
└── frontend/
    └── src/
        ├── App.tsx          # Routes: / (Scanner), /watchlists, /stock/:symbol
        ├── pages/           # ScannerPage, WatchlistPage, StockDetailPage
        ├── components/
        │   ├── scanner/     # ResultsTable, ProfileFilterTabs, ProfileBadge, RowExpansion
        │   ├── stock/       # CandlestickChart, ChartControls, CategoryScores, SignalsPanel,
        │   │                #   HarmonicBanner, ChartPatternsBanner, ElliottWaveBanner
        │   └── watchlist/   # WatchlistList, WatchlistDetail, AddSymbolInput, SAImportButton
        ├── stores/          # scannerStore, stockStore, watchlistStore (Zustand)
        ├── api/             # scanner.ts, watchlists.ts (typed fetch clients)
        ├── hooks/           # useEWPatterns
        ├── types/index.ts   # Shared TypeScript types
        └── __tests__/       # Vitest + React Testing Library tests (co-located in src/)
```

## Analysis Pipeline (`backend/app/analysis/`)

This is the core of the application. The pipeline is pure-sync (`run_analysis`) wrapped in async DB helpers.

```
analysis/
├── pipeline.py          # Orchestrator: run_analysis(), run_scanner(), run_analysis_for_ticker()
├── scoring.py           # build_composite(): signals → category_scores + composite (-1 to +1)
├── profiles.py          # evaluate_profiles(): match scan profiles against scores
├── swing_points.py      # detect_swing_points() — shared infra for EW, Fib, divergence, S/R
├── chart_renderer.py    # mplfinance chart rendering for YOLO inference input
├── yolo_screener.py     # YoloDetection, run_yolo_inference() — YOLOv8 pattern inference
├── yolo_scanner.py      # Nightly background job: render charts → YOLO → pattern_detections table
└── indicators/
    ├── trend.py          # EMA, ADX, Supertrend
    ├── momentum.py       # RSI, MACD, Stochastic
    ├── volatility.py     # Bollinger Bands, ATR, TTM Squeeze
    ├── volume.py         # OBV, VWAP, CMF
    ├── support_resistance.py  # Fibonacci, Pivot Points
    ├── divergence.py     # RSI divergence, MACD divergence
    ├── patterns.py       # Candlestick patterns
    ├── harmonics.py      # HarmonicMatch, detect_harmonics(), pyharmonics integration
    └── elliott_wave.py   # ElliottWaveAnalyzer, detect_elliott_waves(), compute_ew_signals()
```

**Pipeline flow:** OHLCV DataFrame → all indicator signal functions → `build_composite()` → `evaluate_profiles()` → `AnalysisResult`. YOLO detections are pre-fetched from `pattern_detections` and merged before scoring. Results cache to `indicator_cache` hypertable.

**Scoring weights:** trend 0.30, momentum 0.20, volume 0.15, volatility 0.10, S/R 0.10, divergence 0.10, pattern 0.05. All signals normalized to -1.0 to +1.0.

**Actionability:** `is_actionable` = True when ≥3 of 7 categories agree with composite direction and |composite| > 0.05.

## Database

PostgreSQL 16 + TimescaleDB. Full DDL: `docs/V001__initial_schema.sql`.

**Hypertables:** `ohlcv` (partitioned by time), `indicator_cache` (90-day retention)

**Core tables:** `symbols`, `sa_ratings`, `watchlists`, `watchlist_items`, `scan_profiles`, `scan_runs`, `scan_results`, `signal_results`, `pattern_detections`, `divergences`, `swing_points`, `ingestion_log`

## Architecture Decisions

- **Scanner-first.** Build the per-stock scanner before backtesting or broad market modules.
- **Layered TA pipeline:** rule-based (EW, harmonics, indicators) → YOLOv8 chart pattern ML → (future) LLM synthesis.
- **YOLO two-step:** nightly `yolo_scanner.py` renders charts via mplfinance, runs YOLOv8 inference, stores to `pattern_detections`. Daytime scanner fetches pre-stored detections — no GPU blocking the request path.
- **Swing point detection** is shared infrastructure — used by Fibonacci, divergence, EW, S/R. Compute once.
- **JSONB for flexibility** — indicator params, scan profile configs, pattern geometry. Adding an indicator is a config change, not a migration.
- **Weekly bars:** aggregated on-the-fly from daily OHLCV when no native weekly rows exist (`aggregate_daily_to_weekly` in pipeline.py).
- **SA ratings** live in `sa_ratings` with snapshot history, not on the `symbols` table.

## Coding Conventions

### Python (Backend)
- Use `uv` for dependency management
- Type hints everywhere — `mypy --strict` compatible
- Pydantic v2 for all schemas and settings
- SQLAlchemy 2.0 style (`mapped_column`, declarative)
- Async for FastAPI routes and DB queries; sync for CPU-bound TA computation (run in thread pool via `loop.run_in_executor`)
- Ruff for linting (`line-length = 100`) and formatting

### TypeScript (Frontend)
- Strict mode, functional components only
- Zustand for global state, TanStack Query for server state
- No `any` — prefer `unknown` + type guards

### General
- Commit messages: conventional commits (`feat:`, `fix:`, `refactor:`, `chore:`)
- No premature abstraction — extract after 3 repetitions
- Error handling: explicit, no silent catches

## Testing

### Backend Test Tiers
- `tests/unit/` — pure logic, no I/O. `@pytest.mark.unit`
- `tests/integration/` — real TimescaleDB via testcontainers. `@pytest.mark.integration`
- `tests/ta_validation/` — golden file comparison vs recorded OHLCV. `@pytest.mark.ta_validation`

### Key Patterns
- **testcontainers:** one TimescaleDB container per session, transaction-per-test with rollback
- **Factory functions** (not raw SQL): `create_symbol(session, ticker="AAPL", ...)` in `tests/factories.py`
- **Synthetic generators:** `gen_uptrend(bars=100, seed=42)` → deterministic OHLCV in `tests/generators.py`
- **Golden files:** `tests/fixtures/golden/{indicator}.json` — regenerate with `--update-golden`
- **Recorded snapshots:** `tests/fixtures/recorded/*.csv` — real market data, never fetched during tests
- Floating-point comparisons: `pytest.approx()` or the golden file tolerance field

### Frontend Tests
- Vitest + React Testing Library + MSW (Mock Service Worker)
- Tests in `src/__tests__/`, setup in `src/test/setup.ts`, MSW handlers in `src/test/mocks/`

### Writing New Tests
- New indicator: add golden file test in `tests/ta_validation/test_indicators.py` (parametrized)
- New API endpoint: integration test with real DB
- New pure service function: unit test; DB-touching: integration test

## What NOT to Do

- Don't implement backtesting or broad market analysis — P2/P3
- Don't use Parabolic SAR, Williams %R, CCI, or PPO — explicitly excluded as redundant
- Don't use Redux (Zustand) or Django (FastAPI) or InfluxDB (TimescaleDB)
- Don't store SA rating data on `symbols` — it lives in `sa_ratings` with snapshot history
- Don't hardcode indicator parameters — everything configurable via scan_profiles JSONB
