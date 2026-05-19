"""Run `camoufox fetch` with the GitHub API requests authenticated.

The upstream camoufox library uses bare `requests.get(...)` to enumerate
releases on https://api.github.com/repos/daijro/camoufox/releases. The
anonymous quota is 60 req/hour per IP and is easy to exhaust in CI / dev.

This wrapper monkey-patches `requests.Session.request` to inject an
`Authorization: Bearer $GITHUB_TOKEN` header on every GitHub call, then
defers to camoufox's own CLI.
"""

import os
import sys
import requests

token = os.environ.get("GITHUB_TOKEN") or ""

if token:
    _orig = requests.Session.request

    def _patched(self, method, url, **kwargs):
        headers = kwargs.get("headers") or {}
        # Only inject when it's a GitHub API call AND no Authorization is
        # already set — be conservative.
        if "api.github.com" in str(url) and "Authorization" not in headers:
            headers["Authorization"] = "Bearer " + token
            kwargs["headers"] = headers
        return _orig(self, method, url, **kwargs)

    requests.Session.request = _patched
    print(f"fetch_browser: GITHUB_TOKEN injected ({len(token)} chars)", file=sys.stderr)
else:
    print("fetch_browser: no GITHUB_TOKEN, falling back to anonymous quota", file=sys.stderr)

# Defer to camoufox CLI (whose module entry-point lives at camoufox.__main__).
import runpy  # noqa: E402

sys.argv = ["camoufox", "fetch"] + sys.argv[1:]
runpy.run_module("camoufox", run_name="__main__")
