#!/usr/bin/env bash
# OSDP Access Control Panel — Build & Run (Bash)
# Usage: ./run.sh [--skip-build] [--dev]

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT/.venv"

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Python 3 is required but was not found on PATH."
    exit 1
fi

SKIP_BUILD=false
DEV_MODE=false
for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=true ;;
        --dev)        DEV_MODE=true ;;
    esac
done

echo "=== OSDP Access Control Panel ==="

# ── Python dependencies ───────────────────────────────────────
echo ""
echo "[1/3] Preparing Python virtual environment..."
cd "$ROOT"
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install -q -r requirements.txt

# ── Frontend build ────────────────────────────────────────────
if [ "$SKIP_BUILD" = false ]; then
    echo ""
    echo "[2/3] Building React frontend..."
    cd "$ROOT/frontend"
    if [ -f package-lock.json ]; then
        npm ci
    else
        npm install
    fi
    npm run build
else
    echo ""
    echo "[2/3] Skipping frontend build (--skip-build)"
fi

# ── Start backend ─────────────────────────────────────────────
echo ""
echo "[3/3] Starting Flask backend on http://localhost:5000"

if [ "$DEV_MODE" = true ]; then
    echo "Dev mode: starting Vite dev server on http://localhost:3000"
    cd "$ROOT/frontend"
    npm run dev &
fi

cd "$ROOT"
exec "$VENV_DIR/bin/python" app.py
