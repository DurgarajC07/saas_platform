# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Pull a pinned uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install system build deps required by some Python packages (e.g. psycopg, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Sync only production deps into an isolated venv — no dev extras
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# libpq is required at runtime by asyncpg; libmagic for python-magic
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libmagic1 && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder (no uv in the final image)
COPY --from=builder /app/.venv /app/.venv

# Copy only what the running process needs
COPY alembic.ini ./
COPY alembic/ alembic/
COPY app/ app/
COPY scripts/ scripts/

EXPOSE 8000

# 4 gunicorn workers with uvicorn event loop — tune -w to match CPU cores
CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]