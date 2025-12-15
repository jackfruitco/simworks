# syntax=docker/dockerfile:1

ARG UV_VERSION=0.9.9
ARG PYTHON_VERSION=3.14

# === UV Stage ===
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# === Builder Stage ===
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_SYSTEM_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_NO_EDITABLE=1

# Copy local packages
COPY packages ./packages

# Install dependencies from the lockfile (read-only)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml,ro \
    --mount=type=bind,source=uv.lock,target=uv.lock,ro \
    uv sync --frozen --compile-bytecode && \
    uv pip list

# === Runtime Base Stage ===
FROM python:${PYTHON_VERSION}-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy Python deps from builder
COPY --from=builder /usr/local /usr/local

# Create user and folders
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home "/nonexistent" \
    --shell "/sbin/nologin" --no-create-home --uid "${UID}" appuser && \
    mkdir -p /app/static /app/media /app/logs /app/docker && \
    chown -R appuser:appuser /app

RUN --mount=type=cache,target=/var/lib/apt/lists \
    --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# === Web Stage ===
FROM base AS web

ARG DJANGO_SETTINGS_MODULE=config.settings.production
ENV DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}

COPY SimWorks /app/SimWorks
COPY --chown=appuser:appuser --chmod=0755 docker/entrypoint.prod.sh /app/docker/entrypoint.sh
COPY --chown=appuser:appuser --chmod=0755 docker/healthcheck.sh /app/docker/healthcheck.sh

WORKDIR /app/SimWorks

RUN --mount=type=cache,target=/root/.cache/uv \
    python manage.py collectstatic --noinput --clear
RUN mkdir -p /app/static && chown -R appuser:appuser /app/static

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=10 CMD /app/docker/healthcheck.sh

USER appuser

ENTRYPOINT ["/app/docker/entrypoint.sh"]
