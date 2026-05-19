# syntax=docker/dockerfile:1.6
#
# camoufox HTTP wrapper for w_popularity.
#
# Base: python:3.11-slim. We pip-install the `camoufox` library, which bundles
# a patched Firefox under the hood. `camoufox fetch` pulls the actual browser
# binary at build time, baked into the image so first request latency stays
# low.
#
# Two cmd modes:
#   * default: `uvicorn server:app --host 0.0.0.0 --port 3000` — production.
#   * `python login_helper.py <profile> <url>` — interactive login. Started
#     under Xvfb + x11vnc by /entrypoint.sh when the first argv is "python"
#     and the second is "login_helper.py".

FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=3000 \
    PROFILES_ROOT=/data/profiles \
    DISPLAY=:99

# System deps:
#   * camoufox / Firefox runtime libs (libdbus, libxkbcommon, libgbm, etc.)
#   * Xvfb + x11vnc for the headed login flow
#   * fonts so rendered pages look realistic to anti-bot fingerprints
#   * curl for the HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    xvfb \
    x11vnc \
    xauth \
    fluxbox \
    fonts-liberation \
    fonts-noto-color-emoji \
    fonts-dejavu \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libnss3 \
    libxss1 \
    libasound2 \
    libxtst6 \
    libgbm1 \
    libxkbcommon0 \
    libpci3 \
    libegl1 \
    libgl1 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxshmfence1 \
    libwayland-client0 \
    libwayland-egl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Pre-download the camoufox browser binary. This dramatically improves first-
# request latency and means the container is self-contained (no runtime fetch
# from GitHub releases, which could fail if network is restricted).
#
# GITHUB_TOKEN build-arg authenticates the binary download (camoufox fetch
# hits api.github.com/repos/daijro/camoufox/releases — anon quota is 60/hr
# per IP and is easily exhausted). Pass via:
#   docker compose build --build-arg GITHUB_TOKEN=$(gh auth token) camoufox
ARG GITHUB_TOKEN=""
ENV GITHUB_TOKEN=${GITHUB_TOKEN}
COPY fetch_browser.py /app/fetch_browser.py
RUN python /app/fetch_browser.py

COPY server.py login_helper.py entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

RUN mkdir -p /data/profiles

EXPOSE 3000 5900

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/healthz || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "3000"]
