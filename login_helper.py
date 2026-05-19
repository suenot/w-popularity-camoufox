"""Interactive login helper.

Run this inside the camoufox container with Xvfb+VNC exposed so the operator
can VNC-attach, complete the login (LinkedIn / Facebook / whatever), and
close the browser. Cookies persist into /data/profiles/<profile>/ via the
same camoufox persistent_context the production server uses.

Usage (from the host):

    docker compose --profile scraping run --rm -p 5900:5900 camoufox \
        python login_helper.py linkedin https://www.linkedin.com/login

Then open vnc://localhost:5900 from macOS, log in, and close the window.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from camoufox.async_api import AsyncCamoufox

PROFILES_ROOT = Path(os.environ.get("PROFILES_ROOT", "/data/profiles"))
_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


async def run(profile: str, url: str) -> None:
    if not _PROFILE_RE.match(profile):
        raise SystemExit(f"invalid profile name: {profile!r}")
    user_data_dir = PROFILES_ROOT / profile
    user_data_dir.mkdir(parents=True, exist_ok=True)

    print(f"[login] profile={profile} url={url}")
    print(f"[login] user_data_dir={user_data_dir}")
    print("[login] complete login in the visible browser window, then close it to save cookies.")

    async with AsyncCamoufox(
        headless=False,
        persistent_context=True,
        user_data_dir=str(user_data_dir),
        humanize=True,
        os=("linux",),
    ) as ctx:
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded")

        # Hold the context open until the operator closes the last page.
        # camoufox/playwright fires no "context closed" event on graceful
        # window-close, so we poll page count.
        while True:
            pages = ctx.pages
            if not pages:
                break
            await asyncio.sleep(1.0)

        cookies = await ctx.cookies()
        print(f"[login] saved {len(cookies)} cookies to {user_data_dir}")


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python login_helper.py <profile> <url>", file=sys.stderr)
        raise SystemExit(2)
    profile, url = sys.argv[1], sys.argv[2]
    asyncio.run(run(profile, url))


if __name__ == "__main__":
    main()
