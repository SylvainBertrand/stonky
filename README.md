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
# Edit .env — set POSTGRES_PASSWORD
```

### 2. Start the database

```bash
docker compose up -d
# Wait for health: docker compose ps
```

### 3. Backend

```bash
cd backend
uv sync                          # Install dependencies
alembic upgrade head             # Run migrations (creates all 13 tables + hypertables)
uvicorn app.main:app --reload    # Start dev server on :8000
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev                      # Start Vite dev server on :5173
```

### 5. Verify

- API health: `GET http://localhost:8000/api/health`
- UI: `http://localhost:5173`

## Project Structure

```
stonky/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── api/
│   │   ├── services/
│   │   └── tasks/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
└── docs/
    └── V001__initial_schema.sql
```

## Common Commands

```bash
# Backend
cd backend && uvicorn app.main:app --reload
cd backend && alembic upgrade head
cd backend && alembic revision --autogenerate -m "description"
cd backend && pytest

# Frontend
cd frontend && npm run dev
cd frontend && npm run build

# Docker
docker compose up -d
docker compose down -v    # Tear down with volumes (destroys data)
```

## Architecture

See [CLAUDE.md](./CLAUDE.md) for full architecture decisions, tech stack, and coding conventions.
