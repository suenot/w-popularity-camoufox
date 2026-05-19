#!/usr/bin/env bash
# Entrypoint for the camoufox container.
#
# Modes:
#   1. Production: `uvicorn server:app ...` — run headless, no Xvfb.
#   2. Interactive login: `python login_helper.py <profile> <url>` — start
#      Xvfb + x11vnc on :5900 so the operator can VNC-attach and complete a
#      manual login. Cookies are persisted into /data/profiles/<profile>/.
#
# We dispatch on argv: if the first non-option arg is `python` AND the second
# arg is `login_helper.py`, we set up Xvfb. Otherwise we exec the cmd
# directly (default uvicorn).
set -euo pipefail

is_login_mode() {
    [ "${1:-}" = "python" ] && [ "${2:-}" = "login_helper.py" ]
}

if is_login_mode "$@"; then
    echo "[entrypoint] login mode — starting Xvfb on ${DISPLAY:-:99} + x11vnc on :5900"
    # Start virtual framebuffer.
    Xvfb "${DISPLAY:-:99}" -screen 0 1280x800x24 -nolisten tcp &
    XVFB_PID=$!
    # Give Xvfb a moment to come up.
    sleep 1
    # Lightweight WM so the headed browser has a usable parent.
    fluxbox >/dev/null 2>&1 &
    # VNC server, no auth (the port is only exposed to the operator's host).
    x11vnc -display "${DISPLAY:-:99}" -nopw -listen 0.0.0.0 -xkb -forever -shared -rfbport 5900 >/dev/null 2>&1 &
    VNC_PID=$!
    echo "[entrypoint] VNC ready: vnc://localhost:5900"
    # On exit, tear down the background processes.
    trap 'kill $VNC_PID $XVFB_PID 2>/dev/null || true' EXIT
fi

exec "$@"
