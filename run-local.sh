#!/usr/bin/env bash
# Run the camoufox wrapper natively on the host (no Docker).
#
# On first run this creates a Python venv in ./.venv, pip-installs
# requirements, and downloads the patched Firefox via `python -m camoufox
# fetch`. Subsequent runs reuse the venv and skip the fetch step.
#
# Usage:
#   ./run-local.sh server               # production wrapper on :3011
#   ./run-local.sh login <profile> <url>  # interactive login (native Firefox)
#
# Examples:
#   ./run-local.sh login linkedin https://www.linkedin.com/login
#   ./run-local.sh login facebook https://www.facebook.com/login
#   ./run-local.sh server
#
# When the wrapper runs locally, the backend (in Docker) reaches it via
# `host.docker.internal:3011`. Set in your .env:
#   CAMOUFOX_URL=http://host.docker.internal:3011
# and `docker compose up -d backend` to pick it up.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

VENV="$HERE/.venv"
PORT="${CAMOUFOX_PORT:-3011}"
PROFILES_ROOT_HOST="$HERE/../data/camoufox-profiles"
mkdir -p "$PROFILES_ROOT_HOST"
export PROFILES_ROOT="$PROFILES_ROOT_HOST"

# --- bootstrap venv on first run ---
# Prefer Python 3.11 (camoufox deps lag behind 3.13/3.14). Fall back to
# whatever python3 is available if 3.11 isn't installed.
PYTHON_BIN="python3"
for candidate in python3.11 python3.12 python3.13; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ ! -d "$VENV" ]; then
    echo "[setup] creating venv at $VENV (using $PYTHON_BIN)"
    "$PYTHON_BIN" -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip --quiet
    "$VENV/bin/pip" install -r requirements.txt
fi

PY="$VENV/bin/python"

# Ensure the patched Firefox is downloaded. `camoufox fetch` is idempotent
# (no-op if cached) and uses GITHUB_TOKEN if set to dodge anon quota.
if [ ! -d "$HOME/Library/Caches/camoufox" ] && [ ! -d "$HOME/.cache/camoufox" ]; then
    if [ -z "${GITHUB_TOKEN:-}" ] && command -v gh >/dev/null 2>&1; then
        export GITHUB_TOKEN="$(gh auth token 2>/dev/null || true)"
    fi
    echo "[setup] downloading camoufox Firefox binary…"
    "$PY" fetch_browser.py
fi

MODE="${1:-server}"

case "$MODE" in
    server)
        echo "[run-local] starting wrapper on :$PORT (PROFILES_ROOT=$PROFILES_ROOT)"
        echo "[run-local] backend should call http://host.docker.internal:$PORT/fetch"
        exec "$VENV/bin/uvicorn" server:app --host 0.0.0.0 --port "$PORT"
        ;;
    login)
        shift
        if [ $# -lt 2 ]; then
            echo "usage: $0 login <profile> <url>" >&2
            exit 2
        fi
        exec "$PY" login_helper.py "$@"
        ;;
    *)
        echo "usage: $0 {server | login <profile> <url>}" >&2
        exit 2
        ;;
esac
