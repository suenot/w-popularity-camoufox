"""HTTP wrapper around camoufox.

POST /fetch  — render `url` with a persistent profile, return the HTML.
GET  /healthz — liveness probe.

A small per-profile asyncio.Lock serializes concurrent calls that share a
profile (camoufox's persistent_context cannot be opened twice against the
same user_data_dir).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional

from camoufox.async_api import AsyncCamoufox
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("camoufox-wrapper")

PROFILES_ROOT = Path(os.environ.get("PROFILES_ROOT", "/data/profiles"))
PROFILES_ROOT.mkdir(parents=True, exist_ok=True)

# Validate profile names: lowercase letters, digits, dash, underscore. Keeps
# the user_data_dir contained to PROFILES_ROOT and blocks path traversal.
_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Per-profile locks. camoufox/Firefox cannot share a single user_data_dir
# across processes, so we serialize calls per profile.
_profile_locks: Dict[str, asyncio.Lock] = {}
_locks_mu = asyncio.Lock()


async def _lock_for(profile: str) -> asyncio.Lock:
    async with _locks_mu:
        lock = _profile_locks.get(profile)
        if lock is None:
            lock = asyncio.Lock()
            _profile_locks[profile] = lock
        return lock


def _profile_dir(profile: str) -> Path:
    if not _PROFILE_RE.match(profile):
        raise ValueError(f"invalid profile name: {profile!r}")
    p = PROFILES_ROOT / profile
    p.mkdir(parents=True, exist_ok=True)
    return p


class FetchRequest(BaseModel):
    url: str = Field(..., description="Absolute URL to fetch.")
    profile: str = Field(..., description="Persistent profile name (cookie jar).")
    wait_for_selector: str = Field("body", description="CSS selector to wait for.")
    timeout_ms: int = Field(20_000, ge=1_000, le=120_000)
    user_agent: Optional[str] = None


class FetchResponse(BaseModel):
    html: str
    status: int
    final_url: str
    title: str
    cookies_present: bool


app = FastAPI(title="w_popularity-camoufox", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/fetch")
async def fetch(req: FetchRequest):
    try:
        user_data_dir = _profile_dir(req.profile)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    lock = await _lock_for(req.profile)
    async with lock:
        try:
            return await _do_fetch(req, user_data_dir)
        except Exception as e:  # noqa: BLE001 — surface everything to the client
            log.exception("fetch failed: %s", e)
            return JSONResponse(status_code=502, content={"error": str(e)})


async def _do_fetch(req: FetchRequest, user_data_dir: Path) -> FetchResponse:
    log.info(
        "fetch start url=%s profile=%s wait_for=%s timeout=%dms",
        req.url, req.profile, req.wait_for_selector, req.timeout_ms,
    )

    # AsyncCamoufox returns a playwright Browser when persistent_context=False,
    # or a BrowserContext when persistent_context=True. Persistent contexts
    # carry cookies/localStorage between runs, which is what we want.
    # CAMOUFOX_HEADLESS=0 (default during current debug) shows a real Firefox
    # window so the operator can watch what the wrapper sees. Set =1 for
    # production once parsers are stable.
    _headless = os.environ.get("CAMOUFOX_HEADLESS", "0") not in ("0", "false", "False", "")
    async with AsyncCamoufox(
        headless=_headless,
        persistent_context=True,
        user_data_dir=str(user_data_dir),
        humanize=False,
        # Desktop fingerprint: Linux UAs make Facebook fall back to mobile UI.
        os=("macos", "windows"),
        # Force a desktop window size (1440×900). camoufox would otherwise
        # pick a random fingerprint that sometimes lands on phone dimensions.
        window=(1440, 900),
    ) as ctx:
        page = await ctx.new_page()
        if req.user_agent:
            # Note: camoufox manages UA itself; we only override when explicitly
            # requested.
            await page.set_extra_http_headers({"User-Agent": req.user_agent})

        # Track the response status of the main navigation. Subresource
        # responses are ignored — we only care about the document.
        main_status: Dict[str, int] = {"v": 0}

        def _on_response(resp):
            try:
                if resp.request.is_navigation_request() and resp.request.frame == page.main_frame:
                    main_status["v"] = resp.status
            except Exception:
                # Playwright sometimes detaches frames mid-navigation. Best-effort.
                pass

        page.on("response", _on_response)

        try:
            await page.goto(req.url, timeout=req.timeout_ms, wait_until="domcontentloaded")
            await page.wait_for_selector(req.wait_for_selector, timeout=req.timeout_ms)
        except Exception as nav_err:
            # Even on navigation timeout the page may have partial content
            # that's still useful (some sites lazy-load forever).
            log.warning("navigation incomplete (%s); returning whatever we got", nav_err)

        try:
            html = await page.content()
        except Exception as content_err:
            raise RuntimeError(f"page.content() failed: {content_err}") from content_err

        final_url = page.url
        try:
            title = await page.title()
        except Exception:
            title = ""

        cookies = await ctx.cookies()
        cookies_present = bool(cookies)

        await page.close()

    log.info(
        "fetch done url=%s status=%d final=%s html=%d cookies=%s",
        req.url, main_status["v"], final_url, len(html), cookies_present,
    )
    return FetchResponse(
        html=html,
        status=main_status["v"] or 200,
        final_url=final_url,
        title=title,
        cookies_present=cookies_present,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "3000")))
