# Kokoro-82M TTS — multi-language neural TTS
# CPU-friendly: 82M params, ~0.4GB VRAM if GPU used, runs acceptably on CPU.
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libsndfile1-dev espeak-ng && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    # TTS config — override via docker-compose environment
    DEFAULT_VOICE=af_heart \
    DEFAULT_SPEED=1.0 \
    DEFAULT_LANG=a \
    # Model cache — mount a volume to persist HuggingFace downloads
    HF_HOME=/app/models

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    espeak-ng && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY server.py .

VOLUME ["/app/models"]

EXPOSE 8880

HEALTHCHECK --interval=20s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8880/health')" || exit 1

# 2 workers — Kokoro is CPU-bound and stateless, scales well horizontally
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8880", \
     "--workers", "2", "--timeout-keep-alive", "30"]
