SHELL := /bin/bash

# Auto-load .env for native dev targets (dev-api, dev-runner, migrate, seed, ...).
# Docker targets ignore this — compose injects its own env.
ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: help install lint typecheck test clean docker-up docker-down \
        dev-api dev-web dev-runner dev migrate pre-commit build-web check-all ci

PY_PACKAGES := apps/api apps/runner packages/core packages/db packages/shared
PY_SRC := apps packages
# Mypy must run per-package because per-package `tests/conftest.py` files all
# resolve to the top-level module name `conftest` under pytest's importlib mode
# (see CI workflow note). Keep this list in sync with `.github/workflows/ci.yml`.
PY_MYPY_TARGETS := apps/api apps/runner packages/agent packages/core packages/db packages/mcp packages/shared

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  %-20s %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Python (uv)

install: ## Install all Python deps + dev + pre-commit hooks
	uv sync --all-extras --dev
	@echo "--- frontend ---"
	cd apps/web && pnpm install && cd ../..
	@echo "--- pre-commit ---"
	uv run pre-commit install --hook-type pre-commit --hook-type pre-push

uv-lock: ## Sync uv.lock with pyproject.toml
	uv lock

lint: ## Ruff check + format check
	uv run ruff check $(PY_SRC)
	uv run ruff format --check $(PY_SRC)

lint-fix: ## Ruff auto-fix + format
	uv run ruff check --fix $(PY_SRC)
	uv run ruff format $(PY_SRC)

typecheck: ## Mypy strict check (per-package to avoid duplicate conftest)
	@set -e; for t in $(PY_MYPY_TARGETS); do echo "--- mypy $$t ---"; uv run mypy $$t; done

test: ## Run all Python tests
	uv run pytest -v

test-cov: ## Run Python tests with coverage
	uv run pytest --cov --cov-report=term-missing -v

test-file: ## Run a specific test file: make test-file f=path/to/test.py
	uv run pytest -v $(f)

##@ Alembic (DB migrations)

migrate: ## Run pending Alembic migrations
	uv run alembic upgrade head

migrate-new: ## Create a new migration: make migrate-new m="description"
	uv run alembic revision --autogenerate -m "$(m)"

migrate-rollback: ## Rollback last migration
	uv run alembic downgrade -1

##@ Frontend (pnpm / web)

dev-web: ## Start Vite dev server (port 3000)
	cd apps/web && pnpm dev

build-web: ## Build frontend for production
	cd apps/web && pnpm build

typecheck-web: ## TypeScript typecheck
	cd apps/web && pnpm typecheck

lint-web: ## ESLint check
	cd apps/web && pnpm lint

test-web: ## Vitest (frontend tests)
	cd apps/web && pnpm test

##@ Dev servers

dev-api: ## Start FastAPI dev server (port 4000, hot-reload)
	uv run uvicorn --factory suitest_api.main:create_app --host 0.0.0.0 --port 4000 --reload

dev-api-docs: ## Open API docs in browser
	open http://localhost:4000/docs

dev-runner: ## Start ARQ worker (runner)
	uv run python -m suitest_runner

##@ Docker Compose

docker-up: ## Boot all services (ZERO tier default)
	docker compose -f infra/docker/docker-compose.yml --profile zero up -d

docker-up-prod: ## Boot services with build
	docker compose -f infra/docker/docker-compose.yml --profile zero up -d --build

docker-up-local: ## Boot with LOCAL tier profile (+Ollama)
	docker compose -f infra/docker/docker-compose.yml --profile local up -d

docker-up-cloud: ## Boot with CLOUD tier profile
	docker compose -f infra/docker/docker-compose.yml --profile cloud up -d

docker-down: ## Stop all services
	docker compose -f infra/docker/docker-compose.yml down

docker-logs: ## Tail logs from all services
	docker compose -f infra/docker/docker-compose.yml logs -f

docker-logs-api: ## Tail API logs only
	docker compose -f infra/docker/docker-compose.yml logs -f api

docker-ps: ## Show running containers
	docker compose -f infra/docker/docker-compose.yml ps

docker-clean: ## Remove containers + volumes (destroys data!)
	docker compose -f infra/docker/docker-compose.yml down -v

docker-build-images: ## Build all Docker images without running
	docker build -f infra/docker/Dockerfile.api -t suitest-api .
	docker build -f infra/docker/Dockerfile.runner -t suitest-runner .
	docker build -f infra/docker/Dockerfile.web -t suitest-web .

##@ Utilities

pre-commit: ## Run pre-commit on all files
	uv run pre-commit run --all-files

clean: ## Clean Python + Node artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name dist -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache 2>/dev/null || true

check-all: lint typecheck lint-web typecheck-web ## Run all linters + typecheckers (no tests)

ci: check-all test test-web ## Run everything CI does (lint + typecheck + test)

##@ Quick start

env: ## Copy .env.example to .env if not exists
	@test -f .env || cp .env.example .env && echo ".env created from .env.example"

seed: ## Seed DB with default data
	uv run python -m scripts.seed

setup: env install migrate seed ## Full fresh setup: env → deps → migrate → seed
