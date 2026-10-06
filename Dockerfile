# syntax=docker/dockerfile:1

# Images are pinned by digest so a rebuild never pulls something unreviewed; Dependabot
# proposes the updates.
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv
FROM denoland/deno:bin-2.9.7@sha256:bc5aa4466e21b6d3021226a85ba2e1911f7c386254d97b9d797903ab74edace2 AS deno
FROM python:3.14-slim-trixie@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151 AS python

FROM python AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/opt/vidbrief
WORKDIR /src
# Dependencies first, so code changes reuse this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python AS runtime
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --user-group --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin vidbrief
COPY --from=deno /deno /usr/local/bin/deno
COPY --from=builder /opt/vidbrief /opt/vidbrief

# The root filesystem can be mounted read-only, so every cache lives in /tmp.
ENV PATH=/opt/vidbrief/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME=/tmp/cache \
    DENO_DIR=/tmp/deno \
    VIDBRIEF_CONTAINER=true \
    VIDBRIEF_HOST=0.0.0.0 \
    VIDBRIEF_PORT=8000

USER vidbrief
WORKDIR /tmp
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['VIDBRIEF_PORT']}/healthz\", timeout=4)"]
CMD ["vidbrief", "serve"]
