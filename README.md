# w-popularity-camoufox

HTTP wrapper around [camoufox](https://github.com/daijro/camoufox) (a stealth
Firefox fork) that powers the LinkedIn and Facebook parsers in
[w_popularity](https://github.com/suenot/w_popularity).

The parser repos POST a target URL to this service, get back rendered HTML
from a logged-in session, and apply the same extractors they would on a
direct fetch. Cookies live in per-profile `user_data_dir`s on a docker
volume; they survive container restarts and are populated by a one-time
interactive login flow.

## API

### `GET /healthz`

```
{"ok": true}
```

### `POST /fetch`

```json
{
  "url": "https://www.linkedin.com/in/suenot/",
  "profile": "linkedin",
  "wait_for_selector": "main",
  "timeout_ms": 20000,
  "user_agent": null
}
```

Response:

```json
{
  "html": "<!doctype html>…",
  "status": 200,
  "final_url": "https://www.linkedin.com/in/suenot/",
  "title": "Eugen Soloviov | LinkedIn",
  "cookies_present": true
}
```

Concurrency: calls that share a `profile` are serialized — camoufox cannot
open the same `user_data_dir` twice. Calls with different profiles run in
parallel.

On failure: HTTP 502 with `{"error": "..."}`.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `PORT` | `3000` | HTTP port inside the container. |
| `PROFILES_ROOT` | `/data/profiles` | Where persistent profiles live. |
| `LOG_LEVEL` | `INFO` | Python logging level. |

## One-time interactive login

Each platform needs a logged-in profile before `/fetch` can return useful
content. Run the helper once per platform with VNC exposed:

```bash
# LinkedIn
docker compose --profile scraping run --rm -p 5900:5900 camoufox \
    python login_helper.py linkedin https://www.linkedin.com/login

# Facebook
docker compose --profile scraping run --rm -p 5900:5900 camoufox \
    python login_helper.py facebook https://www.facebook.com/login
```

On macOS, attach with:

```bash
open vnc://localhost:5900
```

In the VNC window, complete the login as you normally would (handle captchas,
2FA, the works). Close the browser window when done — the helper waits for
the last page to be closed, then prints how many cookies it persisted.

After that, the production `POST /fetch` reuses the saved profile silently.

## Running standalone

```bash
docker build -t w-popularity-camoufox .
docker run --rm -p 3001:3000 -v $(pwd)/data:/data w-popularity-camoufox
curl -sf http://localhost:3001/healthz
```

## Why this exists

LinkedIn and Facebook personal-profile pages do not expose follower counts
to anonymous HTTP clients. LinkedIn returns HTTP 999 + an authwall stub for
~every UA, and Facebook 302s every public-profile path to `/login`. Even
with a session cookie sent as a raw `Cookie:` header, both platforms run
fingerprint checks that a plain Go `net/http` client cannot defeat. camoufox
spoofs the entire stack — TLS, navigator.*, WebGL, canvas, audio — which is
what gets us past their bot detection in practice.

## Layout

```
camoufox/
├── Dockerfile            # python:3.11-slim + Xvfb/x11vnc + camoufox + Firefox
├── entrypoint.sh         # dispatches: uvicorn (default) | login_helper (Xvfb)
├── requirements.txt      # fastapi, uvicorn, camoufox, pydantic
├── server.py             # POST /fetch, GET /healthz
├── login_helper.py       # interactive login CLI (headed + VNC)
└── README.md
```
