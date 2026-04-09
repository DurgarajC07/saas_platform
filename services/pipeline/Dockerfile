# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Service — AI Voice Call Engine
# Base: python:3.11-slim  (onnxruntime / aiortc wheels exist for cp311)
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# System libs needed to compile aiortc (libopus, libvpx) + soundfile
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libopus-dev \
        libvpx-dev \
        libffi-dev \
        libssl-dev \
        libsndfile1-dev \
        ffmpeg \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

ARG INSTALL_DEEPFILTERNET=0
ARG INSTALL_RNNOISE=0
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
    # Stage 1 noise removal: RNNoise (<1 ms, ~1 MB)
 && if [ "${INSTALL_RNNOISE:-0}" = "1" ]; then \
        pip install --no-cache-dir rnnoise-python; \
    fi \
    # Stage 2 noise removal: DeepFilterNet (~5 ms, pulls PyTorch ~750 MB)
 && if [ "${INSTALL_DEEPFILTERNET:-0}" = "1" ]; then \
        pip install --no-cache-dir deepfilternet; \
    fi

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Runtime system libs only
RUN apt-get update && apt-get install -y --no-install-recommends \
        libopus0 \
        libvpx9 \
        libsndfile1 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy source
COPY . .

EXPOSE 7000

HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:7000/health')"

# Single worker — each session owns an async pipeline; concurrency is via asyncio
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7000", \
     "--workers", "1", "--loop", "uvloop"]
