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
source .venv/bin/activate    # Activate backend environment
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

## Service Mode (Production)

Use the NSSM-managed Windows service when you want Stonky to run **unattended** —
surviving reboots, auto-restarting on crash, and controlled by the Trading Company
Release Manager (TC-002b).  For daily development with hot-reload, keep using
`start-backend.sh` — both modes are fully supported and non-exclusive.

### Prerequisites

- Windows 10/11
- PowerShell 5.1+ (ships with Windows)
- Admin access (required for first install only)
- `uv` on PATH
- Docker running with Postgres up (`docker compose up -d`)
- `.env` present at the repo root (`cp .env.example .env`)

### Installation (first-time or reinstall)

Open an **elevated** PowerShell prompt (right-click → Run as Administrator):

```powershell
cd C:\Users\sylva\my-software-projects\stonky
.\scripts\install-stonky-service.ps1
```

The script will:
1. Download and install NSSM 2.24 to `C:\Program Files\nssm\` if not present.
2. Register `stonky-backend` as a Windows service (autostart, restart-on-crash).
3. Grant the current user (the account that ran the install) service-control rights via SDDL,
   so that future `Stop-Service` / `Start-Service` calls work from a non-elevated shell with
   no UAC prompt.
4. Start the service.
5. Wait 15 seconds, then verify `GET /api/health` returns 200.

### Management

```powershell
# Start / stop / check status (PowerShell or cmd)
net start stonky-backend
net stop  stonky-backend
sc query  stonky-backend

# Restart with health verification (used by Release Manager)
.\scripts\restart-stonky-service.ps1      # PowerShell
./scripts/restart-stonky-service.sh       # Git Bash

# Remove the service completely (logs preserved)
.\scripts\uninstall-stonky-service.ps1
```

> **After the initial elevated install**, all Management commands above work from any
> shell (PowerShell, cmd, Git Bash) owned by the same user — no elevation or UAC prompt
> required.  Uninstall is the one exception: removing a service always requires admin.

### Log locations

| Stream | Path |
|--------|------|
| Stdout | `C:\Users\sylva\my-software-projects\stonky\logs\stonky-backend.out.log` |
| Stderr | `C:\Users\sylva\my-software-projects\stonky\logs\stonky-backend.err.log` |

Logs rotate on service restart; the 10 most recent rotations are kept.

### Troubleshooting

**Service won't start:**
```powershell
# View Windows event log entries from NSSM
Get-EventLog -LogName Application -Source nssm -Newest 10

# Check stderr for Python/uvicorn errors
Get-Content "C:\Users\sylva\my-software-projects\stonky\logs\stonky-backend.err.log" -Tail 50
```

**Health check fails after install:**
Postgres must be running before Stonky starts.
```bash
docker compose up -d        # start Postgres
net start stonky-backend    # then start Stonky
```

**Port 8000 already in use:**
Stop any manually started uvicorn (`start-backend.sh`) before the service starts,
or kill the process via Task Manager / `Get-Process -Name python | Stop-Process`.

**`Access is denied` on `Stop-Service` / `Start-Service`:**
The service was installed before the SDDL grant (TC-002c) was added, or the install
was run as a different user than the one calling restart.  Re-run the install script
from an elevated PowerShell to re-register the service with the correct ACL:
```powershell
.\scripts\install-stonky-service.ps1
```

### Dev mode vs service mode

| | Dev mode | Service mode |
|---|---|---|
| How to start | `./start-backend.sh` | `net start stonky-backend` |
| Hot reload | Yes (`--reload`) | No |
| Survives reboot | No | Yes (autostart) |
| Auto-restarts on crash | No | Yes |
| Runs alembic migrations | Yes | No — run separately |
| Runs ruff format/check | Yes | No |
| Used by Release Manager | No | Yes |

> **Note:** `start-backend.sh` runs `alembic upgrade head` and ruff on every start —
> useful in dev, but the service skips these to keep restarts fast and predictable.
> Run migrations explicitly with `cd backend && uv run alembic upgrade head` before
> deploying new code.

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
| GET | `/api/synthesis/{symbol}` | Latest LLM synthesis for a symbol |
| POST | `/api/synthesis/scan` | Trigger synthesis scan (background) |
| GET | `/api/synthesis/scan/status` | Synthesis scan status |

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

## LLM Synthesis Agent Setup

The synthesis agent uses a local LLM (via Ollama) to generate trade setup analysis from all computed signals.

### Install Ollama

1. Install Ollama: https://ollama.com
2. Pull the default model: `ollama pull llama3.1:8b`
3. Ensure Ollama is running before starting Stonky: `ollama serve`

### RTX 5070 / Blackwell GPU

Ollama may require a recent build for full Blackwell (RTX 50xx) CUDA support.
Check `ollama --version` and update if inference falls back to CPU.
Verify GPU is being used: `ollama run llama3.1:8b "hello"` should show GPU utilization.

### Configuration

Set in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | LLM backend (`ollama` or `claude`) |
| `OLLAMA_MODEL` | `llama3.1:8b` | Ollama model name (try `mistral:7b` as alternative) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `ANTHROPIC_API_KEY` | — | Required when `LLM_PROVIDER=claude` |

The synthesis scan runs nightly at 9 AM ET (after YOLO, EW, and Chronos jobs). It can also be triggered manually via the "Run Analysis" button in the scanner UI or `POST /api/synthesis/scan`.

## Architecture

See [CLAUDE.md](./CLAUDE.md) for full architecture decisions, tech stack, and coding conventions.
