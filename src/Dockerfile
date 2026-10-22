# syntax=docker/dockerfile:1.7
# Backend image: FastAPI + uv
# Build context is the repo root (needs pyproject.toml, uv.lock, alembic.ini):
#   docker build -f src/Dockerfile .
# Ignore rules: src/Dockerfile.dockerignore (BuildKit picks it up next to this file)
#   target "dev"     -> hot reload, dev deps, source bind-mounted by compose
#   target "runtime" -> production: no dev deps, non-root, multiple workers (default)

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.13.1

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------- base
FROM python:${PYTHON_VERSION}-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # venv lives outside /app so a source bind-mount never hides it
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# ---------------------------------------------------------------- builder
FROM base AS builder

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------- dev
FROM builder AS dev

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

EXPOSE 8088
CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8088", "--reload"]

# ---------------------------------------------------------------- runtime
FROM base AS runtime

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --no-create-home app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app src/app ./src/app
COPY --chown=app:app src/db_migration ./src/db_migration

USER app

# uvicorn reads worker count from WEB_CONCURRENCY
ENV ENVIRONMENT=production \
    WEB_CONCURRENCY=2

EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8088/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "src.app.main:app", \
     "--host", "0.0.0.0", "--port", "8088", \
     "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--no-server-header"]
