# Stonky

Personal investment analysis web app. Scanner-first architecture: run configurable TA pipelines on a curated watchlist, score and rank results, surface high-reward/low-risk setups.

## Prerequisites

- Docker + Docker Compose
- Python 3.12+ with `uv` (`pip install uv`)
- Node.js 20+

## Quick Start

### 1. Environment

```bash
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD (and update DATABASE_URL to match)
```

> **Note:** `CORS_ORIGINS` must be a JSON array: `["http://localhost:5173"]`

### 2. Start the database

```bash
docker compose up -d
# Confirm healthy: docker compose ps
```

### 3. Backend

```bash
cd backend
uv sync --extra dev          # Install all dependencies
alembic upgrade head         # Create all 14 tables + hypertables
uvicorn app.main:app --reload  # Dev server on :8000
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev                  # Vite dev server on :5173
```

Open `http://localhost:5173`.

### 5. Load data and run a scan

The app needs symbols + OHLCV data before the scanner can return results.

**Option A — via API (curl)**

```bash
# Create a watchlist
curl -s -X POST http://localhost:8000/api/watchlists \
  -H "Content-Type: application/json" \
  -d '{"name":"Default","is_default":true}'
# → note the returned "id" (e.g. 1)

# Add symbols
for ticker in AAPL MSFT NVDA SPY; do
  curl -s -X POST http://localhost:8000/api/watchlists/1/symbols \
    -H "Content-Type: application/json" \
    -d "{\"ticker\":\"$ticker\"}"
done

# Fetch OHLCV data (background job, ~5-10 s for 4 symbols)
curl -s -X POST http://localhost:8000/api/watchlists/1/refresh

# Run the scanner (background job, ~5 s)
curl -s -X POST http://localhost:8000/api/scanner/run
```

**Option B — via Swagger UI**

Go to `http://localhost:8000/docs` and use the interactive API docs to perform the same steps.

After the scan finishes, refresh `http://localhost:5173` to see ranked results.

## Project Structure

```
stonky/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   └── app/
│       ├── main.py
│       ├── config.py          # Reads .env from repo root
│       ├── analysis/          # TA pipeline (indicators, scoring, profiles)
│       ├── api/               # FastAPI routers
│       │   ├── scanner.py     # /api/scanner/*
│       │   ├── stocks.py      # /api/stocks/{symbol}/ohlcv
│       │   └── watchlist.py   # /api/watchlists/*
│       ├── ingestion/         # yfinance data fetching
│       ├── models/
│       └── schemas/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts         # Proxies /api → :8000
│   └── src/
│       ├── pages/             # ScannerPage, StockDetailPage
│       ├── components/        # Table, chart, signals panels
│       ├── stores/            # Zustand: scannerStore, stockStore
│       └── api/               # Typed API client
└── docs/
    └── V001__initial_schema.sql
```

## API Overview

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health + DB check |
| GET | `/api/watchlists` | List watchlists |
| POST | `/api/watchlists` | Create watchlist |
| POST | `/api/watchlists/{id}/symbols` | Add ticker to watchlist |
| POST | `/api/watchlists/{id}/refresh` | Fetch OHLCV data (background) |
| GET | `/api/watchlists/{id}/status` | Ingestion status per symbol |
| POST | `/api/scanner/run` | Run full watchlist scan (background) |
| POST | `/api/scanner/run/{symbol}` | Run on-demand scan for one symbol |
| GET | `/api/scanner/results` | Latest ranked results (`?profile=` filter) |
| GET | `/api/scanner/results/{symbol}` | Full detail for one ticker |
| GET | `/api/scanner/profiles` | List scan profiles |
| GET | `/api/stocks/{symbol}/ohlcv` | OHLCV bars + EMA/Supertrend overlays |

Full interactive docs at `http://localhost:8000/docs`.

## Common Commands

```bash
# Backend
cd backend && uvicorn app.main:app --reload
cd backend && alembic upgrade head
cd backend && uv run --extra dev python -m pytest -m unit
cd backend && uv run --extra dev python -m pytest -m integration   # needs Docker

# Frontend
cd frontend && npm run dev
cd frontend && npm run build
cd frontend && npm test -- --run

# Docker
docker compose up -d
docker compose down -v    # Tear down with volumes (destroys all data)
```

## Architecture

See [CLAUDE.md](./CLAUDE.md) for full architecture decisions, tech stack, and coding conventions.
