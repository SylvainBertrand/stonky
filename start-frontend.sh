#!/usr/bin/env bash
# Start the Stonky frontend (Vite dev server).
# Kills any running instance, rebuilds, then starts dev server.
# Works from stonky/, backend/, or frontend/ directories.

set -euo pipefail

# Resolve repo root regardless of where the script is called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
  REPO_ROOT="$SCRIPT_DIR"
elif [[ -f "$SCRIPT_DIR/../docker-compose.yml" ]]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  REPO_ROOT="$SCRIPT_DIR"
fi

FRONTEND_DIR="$REPO_ROOT/frontend"

# Kill any running vite dev server instances
if pids=$(pgrep -f "vite" 2>/dev/null | head -5); then
  echo "Killing existing Vite process(es): $pids"
  kill $pids 2>/dev/null || true
  sleep 1
fi

cd "$FRONTEND_DIR"

# Install deps if needed
if [[ ! -d "node_modules" ]] || [[ "package.json" -nt "node_modules/.package-lock.json" ]]; then
  echo "Installing dependencies..."
  npm install
fi

# Build to catch TypeScript errors
echo "Building frontend..."
npm run build

echo "Starting dev server..."
exec npm run dev
