# ── Stage 1: dependency builder ───────────────────────────────────────────────
# Use a full CUDA dev image to compile packages that need CUDA headers at build time.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-dev python3.11-venv python3-pip \
    build-essential pkg-config && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create isolated venv and install deps
RUN python3.11 -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Stage 2: slim runtime ─────────────────────────────────────────────────────
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    # Model config — override at runtime via env or docker-compose
    MODEL=large-v3-turbo \
    DEVICE=cuda \
    COMPUTE_TYPE=float16 \
    NUM_WORKERS=2 \
    # Model cache — mount a volume here to persist the download
    HF_HOME=/app/models \
    WHISPER_CACHE=/app/models

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    ffmpeg \
    libsndfile1 \
    libgomp1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY server.py .

# Model cache volume — large-v3-turbo is ~1.5GB, downloads on first start
VOLUME ["/app/models"]

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python3.11 -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/health')" || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000", \
     "--workers", "1", "--timeout-keep-alive", "75"]
