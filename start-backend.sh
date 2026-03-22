#!/usr/bin/env bash
# Start the Stonky backend (FastAPI + uvicorn).
# Kills any running instance, runs alembic migrations, then starts with --reload.
# Works from stonky/, backend/, or frontend/ directories.

set -euo pipefail

# Resolve repo root regardless of where the script is called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# If invoked via a symlink or from a subdirectory, find the repo root
if [[ -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
  REPO_ROOT="$SCRIPT_DIR"
elif [[ -f "$SCRIPT_DIR/../docker-compose.yml" ]]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  REPO_ROOT="$SCRIPT_DIR"
fi

BACKEND_DIR="$REPO_ROOT/backend"

# Kill any running uvicorn instances
if pids=$(pgrep -f "uvicorn app.main:app" 2>/dev/null); then
  echo "Killing existing uvicorn process(es): $pids"
  kill $pids 2>/dev/null || true
  sleep 1
  # Force kill if still alive
  if pgrep -f "uvicorn app.main:app" >/dev/null 2>&1; then
    kill -9 $(pgrep -f "uvicorn app.main:app") 2>/dev/null || true
  fi
fi

cd "$BACKEND_DIR"

# Run alembic migrations
echo "Running alembic migrations..."
uv run alembic upgrade head

# Lint + format (non-fatal — pre-existing warnings shouldn't block startup)
echo "Running ruff format..."
uv run ruff format app/
echo "Running ruff check..."
uv run ruff check app/ --fix || true

echo "Starting backend..."
exec uv run uvicorn app.main:app --reload
