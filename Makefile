.PHONY: help install dev run migrate revision seed test lint format docker-up docker-down

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