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
PNPM ?= $(shell which pnpm 2>/dev/null || echo "npx -y pnpm")

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  %-20s %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Python (uv)

install: ## Install all Python deps + dev + pre-commit hooks
	# --all-packages, not just the root: without it the workspace members
	# (suitest_mcp, suitest_api, ...) are never installed into .venv and every
	# test that imports one fails at collection with ModuleNotFoundError.
	uv sync --all-extras --dev --all-packages
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

dev-web: ## Start Vite dev server (port 3000, or VITE_PORT from env)
	cd apps/web && VITE_PORT=$${VITE_PORT:-3000} VITE_BACKEND_PORT=$${VITE_BACKEND_PORT:-$${SUITEST_API_PORT:-4000}} $(PNPM) dev

build-web: ## Build frontend for production
	cd apps/web && $(PNPM) build

typecheck-web: ## TypeScript typecheck
	cd apps/web && $(PNPM) typecheck

lint-web: ## ESLint check
	cd apps/web && $(PNPM) lint

test-web: ## Vitest (frontend tests)
	cd apps/web && $(PNPM) test

e2e-real: ## Real-backend dogfood e2e: seed ZERO state, boot api+web+runner, drive the UI
	@export SUITEST_DATABASE_URL="$${SUITEST_DATABASE_URL:-postgresql+asyncpg://suitest:suitest@localhost:5432/suitest_e2e}"; \
	echo "Running E2E tests against isolated database: $$SUITEST_DATABASE_URL"; \
	uv run python apps/api/scripts/seed_zero_e2e.py && \
	uv run alembic upgrade head && \
	npx -y @playwright/mcp@latest --version >/dev/null 2>&1 || true; \
	SUITEST_OTEL_DISABLED=true SUITEST_DATABASE_URL="$$SUITEST_DATABASE_URL" uv run python -m suitest_runner > /tmp/suitest_e2e_runner.log 2>&1 & \
	RUNNER_PID=$$!; \
	trap "kill $$RUNNER_PID 2>/dev/null" EXIT INT TERM; \
	cd apps/web && SUITEST_DATABASE_URL="$$SUITEST_DATABASE_URL" $(PNPM) exec playwright test --config=playwright.realbackend.config.ts

SUITEST_API_PORT ?= 4000

##@ Dev servers

dev-api: ## Start FastAPI dev server (port 4000, or SUITEST_API_PORT from env)
	uv run uvicorn --factory suitest_api.main:create_app --host 0.0.0.0 --port $(SUITEST_API_PORT) --reload

dev-api-zero: ## Start FastAPI at the ZERO base (default; LLM is workspace-configured via the web UI)
	uv run uvicorn --factory suitest_api.main:create_app --host 0.0.0.0 --port $(SUITEST_API_PORT)

dev-api-docs: ## Open API docs in browser
	open http://localhost:$(SUITEST_API_PORT)/docs

dev-runner: ## Start runner (local supervisor in local mode or SQLite DB, ARQ worker in server mode)
	@if [ "$$(echo $${SUITEST_MODE})" = "local" ] || echo "$${SUITEST_DATABASE_URL}" | grep -q "sqlite"; then \
		uv run python -m suitest_runner.local_supervisor; \
	else \
		uv run python -m suitest_runner; \
	fi

dev-runner-local: ## Start LOCAL-mode run supervisor (SQLite polling, no Redis)
	uv run python -m suitest_runner.local_supervisor

dev: ## Start API + web + runner together (Ctrl-C stops all)
	@echo "Starting API ($(SUITEST_API_PORT)), web ($${VITE_PORT:-3000}), runner..."
	@trap 'kill 0' EXIT INT TERM; \
	$(MAKE) dev-api & \
	$(MAKE) dev-web & \
	$(MAKE) dev-runner & \
	wait

##@ Docker Compose

docker-up: ## Boot all services (ZERO tier default; pulls prebuilt ghcr images, builds only as fallback)
	-docker compose -f infra/docker/docker-compose.yml --profile zero pull --ignore-pull-failures
	docker compose -f infra/docker/docker-compose.yml --profile zero up -d

docker-up-prod: ## Boot services with a local image build (skip ghcr)
	docker compose -f infra/docker/docker-compose.yml --profile zero up -d --build

docker-up-local: ## Boot with LOCAL tier profile (+Ollama)
	-docker compose -f infra/docker/docker-compose.yml --profile local pull --ignore-pull-failures
	docker compose -f infra/docker/docker-compose.yml --profile local up -d

docker-up-cloud: ## Boot with CLOUD tier profile
	-docker compose -f infra/docker/docker-compose.yml --profile cloud pull --ignore-pull-failures
	docker compose -f infra/docker/docker-compose.yml --profile cloud up -d

docker-down: ## Stop all services
	docker compose -f infra/docker/docker-compose.yml down

demo: ## Boot full stack + Brewly demo app + seeded runnable suite
	@test -f .env || (cp .env.example .env && echo ".env created from .env.example")
	docker compose --env-file .env -f infra/docker/docker-compose.yml --profile demo up -d --build
	@echo ""
	@echo "  Suitest demo ready:"
	@echo "  Web       http://localhost:3000  (demo@suitest.dev / demo1234)"
	@echo "  Brewly    http://localhost:8089"
	@echo ""
	@echo "  Open Test Cases -> 'Brewly — generated from PRD.md' -> Run."
	@echo ""

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

local-smoke: ## M4-1: boot CPU Ollama, pull tiny model, smoke the LOCAL tier provider
	./scripts/local-tier-smoke.sh

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
	uv run python -m suitest_db.seed

setup: env install migrate seed ## Full fresh setup: env → deps → migrate → seed
