.PHONY: help install dev run migrate revision seed test lint format \
        docker-up docker-down \
        infra-up infra-down infra-logs infra-ps infra-build infra-restart \
        nvidia-docker-setup \
        whisper-test tts-test qdrant-test

help: ## Show help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production deps
	uv sync --frozen

dev: ## Install all deps (including dev)
	uv sync --frozen --all-extras

run: ## Run dev server with reload
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

migrate: ## Run alembic upgrade head
	uv run alembic upgrade head

revision: ## Create new migration. Usage: make revision m="add users table"
	uv run alembic revision --autogenerate -m "$(m)"

seed: ## Seed permissions & plans
	uv run python -m scripts.seed_permissions
	uv run python -m scripts.seed_plans

superuser: ## Create platform superuser
	uv run python -m scripts.create_superuser

test: ## Run tests
	uv run pytest -v --cov=app --cov-report=term-missing

lint: ## Lint with ruff
	uv run ruff check app tests

format: ## Format with ruff
	uv run ruff format app tests

docker-up: ## Start containers
	docker compose up -d --build

docker-down: ## Stop containers
	docker compose down -v

# ─────────────────────────────────────────────────────────────────────────────
#  AI Infrastructure  (Whisper, Kokoro, Qdrant, MinIO)
#  Prerequisites: NVIDIA Container Toolkit installed — run `make nvidia-docker-setup`
# ─────────────────────────────────────────────────────────────────────────────

INFRA_COMPOSE := docker compose -f docker-compose.infra.yml --env-file .env.ai

# Ensure .env.ai exists; if not, copy from example and remind the user.
.env.ai:
	@if [ ! -f .env.ai ]; then \
		cp .env.ai.example .env.ai; \
		echo ""; \
		echo "  ┌──────────────────────────────────────────────────────────┐"; \
		echo "  │  .env.ai created from .env.ai.example                    │"; \
		echo "  │  Review and edit it before running infra-up.             │"; \
		echo "  └──────────────────────────────────────────────────────────┘"; \
		echo ""; \
	fi

infra-up: .env.ai ## Build and start all AI infra services (Whisper, Kokoro, Qdrant, MinIO)
	$(INFRA_COMPOSE) up -d --build
	@echo ""
	@echo "  Services started:"
	@echo "    Whisper STT  → http://localhost:9001/docs"
	@echo "    Kokoro TTS   → http://localhost:8881/docs"
	@echo "    Qdrant       → http://localhost:6333/dashboard"
	@echo "    MinIO UI     → http://localhost:9101  (API: :9100)"
	@echo ""
	@echo "  Tip: model weights download on first start — takes 2–5 minutes."
	@echo "  Run 'make infra-logs' to watch progress."

infra-down: ## Stop and remove AI infra containers (preserves volumes)
	$(INFRA_COMPOSE) down

infra-build: .env.ai ## Rebuild AI service images without starting
	$(INFRA_COMPOSE) build --no-cache

infra-logs: ## Tail logs for all AI infra services
	$(INFRA_COMPOSE) logs -f --tail=50

infra-ps: ## Show running AI infra containers and their health
	$(INFRA_COMPOSE) ps

infra-restart: ## Restart a specific service. Usage: make infra-restart svc=whisper-1
	$(INFRA_COMPOSE) restart $(svc)

# ── Smoke tests ──────────────────────────────────────────────────────────────

whisper-test: ## Smoke-test the Whisper STT service (requires a WAV file at /tmp/test.wav)
	@echo "Testing Whisper STT on whisper-1 (port 9001)..."
	curl -s http://localhost:9001/health | python3 -m json.tool
	curl -s http://localhost:9001/info | python3 -m json.tool
	@if [ -f /tmp/test.wav ]; then \
		curl -s -X POST http://localhost:9001/transcribe \
		     -F "file=@/tmp/test.wav" \
		     -F "language=en" | python3 -m json.tool; \
	else \
		echo "(skipping file transcription — /tmp/test.wav not found)"; \
	fi

tts-test: ## Smoke-test the Kokoro TTS service (saves output to /tmp/tts_test.wav)
	@echo "Testing Kokoro TTS on kokoro-1 (port 8881)..."
	curl -s http://localhost:8881/health | python3 -m json.tool
	curl -s -X POST http://localhost:8881/tts \
	     -H "Content-Type: application/json" \
	     -d '{"text":"Hello, this is a test of the Kokoro text to speech system.", "voice":"af_heart"}' \
	     --output /tmp/tts_test.wav && echo "  Audio saved to /tmp/tts_test.wav"

qdrant-test: ## Smoke-test Qdrant — list collections
	@echo "Testing Qdrant (port 6333)..."
	curl -s http://localhost:6333/healthz
	@echo ""
	curl -s http://localhost:6333/collections | python3 -m json.tool

# ── NVIDIA Docker runtime setup ───────────────────────────────────────────────

nvidia-docker-setup: ## Install and configure NVIDIA Container Toolkit for Docker (run as sudo if needed)
	@echo "Installing NVIDIA Container Toolkit..."
	@if command -v apt-get &>/dev/null; then \
		curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
		  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg; \
		curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
		  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
		  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list; \
		sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit; \
	elif command -v dnf &>/dev/null; then \
		curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo | \
		  sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo; \
		sudo dnf install -y nvidia-container-toolkit; \
	else \
		echo "Unsupported distro — install nvidia-container-toolkit manually."; \
		exit 1; \
	fi
	@echo "Configuring Docker runtime..."
	sudo nvidia-ctk runtime configure --runtime=docker
	sudo systemctl restart docker
	@echo ""
	@echo "Verifying..."
	docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi