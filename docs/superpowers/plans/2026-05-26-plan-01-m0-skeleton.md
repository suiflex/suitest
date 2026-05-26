# M0 — Skeleton Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap empty repo into deployable monorepo with FastAPI + Vite shells, Postgres + Redis + MinIO running via docker-compose, Alembic init migration, OAuth login flow, capability endpoint returning ZERO tier, GitHub Actions CI green. No product features yet.

**Architecture:** Polyglot monorepo — Python apps managed by `uv` workspace (`apps/api`, `apps/runner`, `packages/*`); TypeScript apps managed by `pnpm` workspace (`apps/web`). Docker-compose for local dev (postgres+pgvector, redis, minio). FastAPI exposes `/health` + `/capabilities`. Vite+React SPA boots to login → empty dashboard with ZERO tier badge. GitHub Actions runs ruff/mypy/pytest for Python and tsc/eslint/vitest for TS.

**Tech Stack:** Python 3.12, uv, FastAPI 0.115+, Uvicorn, Pydantic v2, SQLAlchemy 2 async, Alembic, asyncpg, Postgres 16 + pgvector, Redis 7, MinIO, FastAPI-Users, Authlib (Google OAuth), Node 20+, pnpm, Vite 6, React 19, TypeScript 5, TanStack Router, TanStack Query, Tailwind 4, shadcn/ui, Zustand, Docker, docker-compose v2, GitHub Actions

---

## Task 0: Repo init + workspace scaffolding

**Acceptance criterion:** M0-1 (monorepo + uv/pnpm workspace).

- [ ] **0.1** Initialize git at repo root:
  ```bash
  git init
  git branch -M main
  ```
  expected:
  ```
  Initialized empty Git repository in /path/to/suitest/.git/
  ```

- [ ] **0.2** Create `.gitignore` at repo root with Python + Node + macOS entries:
  ```gitignore
  # Python
  __pycache__/
  *.py[cod]
  *$py.class
  *.so
  .Python
  .venv/
  venv/
  env/
  .pytest_cache/
  .mypy_cache/
  .ruff_cache/
  .coverage
  htmlcov/
  *.egg-info/
  dist/
  build/

  # uv
  .uv/
  uv.lock.bak

  # Node
  node_modules/
  .pnpm-store/
  pnpm-debug.log*
  npm-debug.log*
  yarn-error.log*
  *.tsbuildinfo
  .turbo/
  .next/
  .vite/

  # OS
  .DS_Store
  Thumbs.db
  ._*
  .Spotlight-V100
  .Trashes

  # IDE
  .vscode/*
  !.vscode/extensions.json
  .idea/
  *.swp
  *.swo

  # Env / secrets
  .env
  .env.local
  .env.*.local
  *.pem
  *.key

  # Build artifacts
  apps/web/dist/
  apps/web/coverage/
  apps/api/.coverage
  apps/runner/.coverage

  # Docker
  .docker/
  ```

- [ ] **0.3** Create root `README.md` stub:
  ```markdown
  # Suitest

  MCP-native testing platform. Manual TCM, deterministic runs, autonomous AI when configured.
  Your stack, your LLM, your data.

  ## Status

  Pre-release. See [docs/ROADMAP.md](./docs/ROADMAP.md). Current milestone: **M0 — Skeleton OSS**.

  ## Quickstart

  ```bash
  cp .env.example .env
  docker compose -f infra/docker/docker-compose.yml --env-file .env --profile zero up -d
  open http://localhost:3000
  ```

  See [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) for full deployment guide.

  ## Documentation

  - [docs/PRODUCT.md](./docs/PRODUCT.md) — product overview
  - [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — tech stack
  - [docs/CAPABILITY_TIERS.md](./docs/CAPABILITY_TIERS.md) — ZERO/LOCAL/CLOUD tiers
  - [docs/ROADMAP.md](./docs/ROADMAP.md) — milestones

  ## License

  Apache 2.0
  ```

- [ ] **0.4** Create directory skeleton:
  ```bash
  mkdir -p apps/api/src/suitest_api apps/api/tests
  mkdir -p apps/runner/src/suitest_runner apps/runner/tests
  mkdir -p apps/web/src/routes apps/web/src/components apps/web/src/lib apps/web/src/stores apps/web/src/styles apps/web/public
  mkdir -p packages/agent/src/suitest_agent packages/agent/tests
  mkdir -p packages/core/src/suitest_core packages/core/tests
  mkdir -p packages/db/src/suitest_db/models packages/db/src/suitest_db/repositories packages/db/alembic/versions packages/db/tests
  mkdir -p packages/mcp/src/suitest_mcp packages/mcp/tests
  mkdir -p packages/shared/src/suitest_shared packages/shared/tests
  mkdir -p infra/docker
  mkdir -p infra/helm/suitest/templates
  mkdir -p docs eval examples
  mkdir -p .github/workflows
  ```

- [ ] **0.5** Create root `pyproject.toml` declaring uv workspace:
  ```toml
  [project]
  name = "suitest-monorepo"
  version = "0.1.0"
  description = "Suitest OSS monorepo root"
  requires-python = ">=3.12,<3.13"

  [tool.uv.workspace]
  members = [
    "apps/api",
    "apps/runner",
    "packages/agent",
    "packages/core",
    "packages/db",
    "packages/mcp",
    "packages/shared",
  ]

  [tool.uv]
  dev-dependencies = [
    "ruff>=0.7.0",
    "mypy>=1.13.0",
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "httpx>=0.27.0",
    "asgi-lifespan>=2.1.0",
    "pre-commit>=4.0.0",
  ]

  [tool.uv.sources]
  suitest-api = { workspace = true }
  suitest-runner = { workspace = true }
  suitest-agent = { workspace = true }
  suitest-core = { workspace = true }
  suitest-db = { workspace = true }
  suitest-mcp = { workspace = true }
  suitest-shared = { workspace = true }
  ```

- [ ] **0.6** Create root `pnpm-workspace.yaml`:
  ```yaml
  packages:
    - "apps/web"
  ```

- [ ] **0.7** Create root `.python-version`:
  ```
  3.12
  ```

- [ ] **0.8** Create root `.node-version`:
  ```
  20
  ```

- [ ] **0.9** Verify scaffolding:
  ```bash
  ls -la
  ```
  expected: directories `apps/`, `packages/`, `infra/`, `docs/`, `eval/`, `examples/`, `.github/` plus files `.gitignore`, `README.md`, `pyproject.toml`, `pnpm-workspace.yaml`, `.python-version`, `.node-version`.

- [ ] **0.10** Initial commit:
  ```bash
  git add -A
  git commit -m "chore(repo): bootstrap monorepo skeleton (uv + pnpm workspaces)"
  ```
  expected:
  ```
  [main (root-commit) ...] chore(repo): bootstrap monorepo skeleton (uv + pnpm workspaces)
  ```

---

## Task 1: Tooling — ruff/mypy/pre-commit (Python) + eslint/prettier (TS)

**Acceptance criterion:** M0-2 (lint/format/typecheck + pre-commit).

- [ ] **1.1** Append ruff + mypy config to root `pyproject.toml`:
  ```toml
  [tool.ruff]
  line-length = 100
  target-version = "py312"
  src = ["apps", "packages"]
  extend-exclude = ["alembic/versions"]

  [tool.ruff.lint]
  select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # pyflakes
    "I",      # isort
    "B",      # bugbear
    "UP",     # pyupgrade
    "ASYNC",  # async correctness
    "RUF",    # ruff-specific
    "SIM",    # simplify
    "TCH",    # type-checking-imports
  ]
  ignore = ["E501"]  # line length handled by formatter

  [tool.ruff.lint.per-file-ignores]
  "**/tests/**/*.py" = ["B018"]

  [tool.ruff.format]
  quote-style = "double"
  indent-style = "space"

  [tool.mypy]
  python_version = "3.12"
  strict = true
  disallow_untyped_defs = true
  disallow_any_unimported = true
  no_implicit_optional = true
  warn_redundant_casts = true
  warn_unused_ignores = true
  warn_return_any = true
  check_untyped_defs = true
  plugins = ["pydantic.mypy"]
  mypy_path = ["apps/api/src", "apps/runner/src", "packages/agent/src", "packages/core/src", "packages/db/src", "packages/mcp/src", "packages/shared/src"]
  explicit_package_bases = true
  namespace_packages = true
  exclude = "(^|/)(\\.venv|alembic/versions|node_modules|dist|build)/"

  [[tool.mypy.overrides]]
  module = ["alembic.*", "fastembed.*"]
  ignore_missing_imports = true

  [tool.pytest.ini_options]
  asyncio_mode = "strict"
  testpaths = ["apps/api/tests", "apps/runner/tests", "packages/core/tests", "packages/db/tests", "packages/mcp/tests", "packages/shared/tests", "packages/agent/tests"]
  addopts = "-ra -q --strict-markers"
  ```

- [ ] **1.2** Create `.pre-commit-config.yaml` at repo root:
  ```yaml
  default_language_version:
    python: python3.12
    node: "20"

  repos:
    - repo: https://github.com/pre-commit/pre-commit-hooks
      rev: v5.0.0
      hooks:
        - id: trailing-whitespace
        - id: end-of-file-fixer
        - id: check-yaml
          args: ["--unsafe"]
        - id: check-added-large-files
          args: ["--maxkb=500"]
        - id: check-merge-conflict
        - id: detect-private-key

    - repo: https://github.com/astral-sh/ruff-pre-commit
      rev: v0.7.4
      hooks:
        - id: ruff
          args: ["--fix"]
        - id: ruff-format

    - repo: https://github.com/pre-commit/mirrors-mypy
      rev: v1.13.0
      hooks:
        - id: mypy
          additional_dependencies:
            - pydantic>=2.9.0
            - sqlalchemy>=2.0.36
            - fastapi>=0.115.0
          args: ["--config-file=pyproject.toml"]
          files: ^(apps|packages)/.*\.py$
          exclude: ^.*/alembic/versions/.*$

    - repo: https://github.com/gitleaks/gitleaks
      rev: v8.21.2
      hooks:
        - id: gitleaks
  ```

- [ ] **1.3** Create `apps/web/.eslintrc.cjs`:
  ```js
  /** @type {import('eslint').Linter.Config} */
  module.exports = {
    root: true,
    env: { browser: true, es2024: true, node: true },
    parser: "@typescript-eslint/parser",
    parserOptions: {
      ecmaVersion: 2024,
      sourceType: "module",
      project: "./tsconfig.json",
      tsconfigRootDir: __dirname,
    },
    plugins: ["@typescript-eslint", "react", "react-hooks", "react-refresh"],
    extends: [
      "eslint:recommended",
      "plugin:@typescript-eslint/recommended-type-checked",
      "plugin:react/recommended",
      "plugin:react/jsx-runtime",
      "plugin:react-hooks/recommended",
      "prettier",
    ],
    settings: { react: { version: "19.0" } },
    rules: {
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/consistent-type-imports": ["error", { prefer: "type-imports" }],
    },
    ignorePatterns: ["dist", "node_modules", "*.config.ts", "*.config.js"],
  };
  ```

- [ ] **1.4** Create `apps/web/.prettierrc`:
  ```json
  {
    "semi": true,
    "singleQuote": false,
    "trailingComma": "all",
    "printWidth": 100,
    "tabWidth": 2,
    "useTabs": false,
    "arrowParens": "always",
    "endOfLine": "lf"
  }
  ```

- [ ] **1.5** Create `apps/web/tsconfig.json`:
  ```json
  {
    "compilerOptions": {
      "target": "ES2022",
      "lib": ["ES2023", "DOM", "DOM.Iterable"],
      "module": "ESNext",
      "moduleResolution": "bundler",
      "allowImportingTsExtensions": false,
      "resolveJsonModule": true,
      "isolatedModules": true,
      "verbatimModuleSyntax": true,
      "esModuleInterop": true,
      "allowSyntheticDefaultImports": true,
      "jsx": "react-jsx",
      "strict": true,
      "noImplicitAny": true,
      "noImplicitReturns": true,
      "noUnusedLocals": true,
      "noUnusedParameters": true,
      "noFallthroughCasesInSwitch": true,
      "noUncheckedIndexedAccess": true,
      "exactOptionalPropertyTypes": true,
      "skipLibCheck": true,
      "forceConsistentCasingInFileNames": true,
      "useDefineForClassFields": true,
      "baseUrl": ".",
      "paths": { "@/*": ["./src/*"] },
      "types": ["vite/client", "vitest/globals"]
    },
    "include": ["src", "vite.config.ts", "vitest.config.ts"],
    "exclude": ["node_modules", "dist"]
  }
  ```

- [ ] **1.6** Install uv dev deps and pre-commit hook (run from repo root):
  ```bash
  uv sync
  uv run pre-commit install
  ```
  expected:
  ```
  pre-commit installed at .git/hooks/pre-commit
  ```

- [ ] **1.7** Verify ruff config compiles (no Python files yet, so lint should pass trivially):
  ```bash
  uv run ruff check .
  uv run ruff format --check .
  ```
  expected:
  ```
  All checks passed!
  ```

- [ ] **1.8** Commit:
  ```bash
  git add -A
  git commit -m "chore(tooling): add ruff/mypy/pre-commit (py) + eslint/prettier (ts) configs"
  ```

---

## Task 2: apps/api FastAPI hello + /health (TDD)

**Acceptance criterion:** M0-4 (FastAPI boot + `GET /health`).

- [ ] **2.1** Create `apps/api/pyproject.toml`:
  ```toml
  [project]
  name = "suitest-api"
  version = "0.1.0"
  description = "Suitest FastAPI HTTP service"
  requires-python = ">=3.12,<3.13"
  dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "structlog>=24.4.0",
    "suitest-core",
    "suitest-shared",
  ]

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/suitest_api"]
  ```

- [ ] **2.2** Create `apps/api/src/suitest_api/__init__.py`:
  ```python
  """Suitest FastAPI HTTP service."""

  __version__ = "0.1.0"
  ```

- [ ] **2.3** Create `apps/api/src/suitest_api/settings.py`:
  ```python
  """Process-level settings sourced from environment."""

  from pydantic import Field
  from pydantic_settings import BaseSettings, SettingsConfigDict


  class Settings(BaseSettings):
      """Top-level config for the API process."""

      model_config = SettingsConfigDict(
          env_prefix="SUITEST_",
          env_file=None,
          extra="ignore",
          case_sensitive=False,
      )

      api_host: str = Field(default="0.0.0.0")
      api_port: int = Field(default=4000)
      web_url: str = Field(default="http://localhost:3000")
      api_url: str = Field(default="http://localhost:4000")
      log_level: str = Field(default="INFO")


  def get_settings() -> Settings:
      """Return a fresh Settings instance (env-resolved)."""
      return Settings()
  ```

- [ ] **2.4** TDD — write the failing test first. Create `apps/api/tests/__init__.py` (empty file) and `apps/api/tests/conftest.py`:
  ```python
  """Shared fixtures for the api test suite."""

  from collections.abc import AsyncIterator

  import pytest
  from asgi_lifespan import LifespanManager
  from httpx import ASGITransport, AsyncClient

  from suitest_api.main import create_app


  @pytest.fixture
  async def client() -> AsyncIterator[AsyncClient]:
      """Return an httpx AsyncClient wired to the ASGI app via lifespan."""
      app = create_app()
      async with LifespanManager(app):
          transport = ASGITransport(app=app)
          async with AsyncClient(transport=transport, base_url="http://test") as c:
              yield c
  ```

- [ ] **2.5** Create `apps/api/tests/test_health.py`:
  ```python
  """Health endpoint contract tests."""

  import pytest
  from httpx import AsyncClient


  @pytest.mark.asyncio
  async def test_health_returns_ok(client: AsyncClient) -> None:
      """GET /health returns 200 + canonical payload."""
      response = await client.get("/health")
      assert response.status_code == 200
      payload = response.json()
      assert payload == {"status": "ok", "service": "api", "version": "0.1.0"}
  ```

- [ ] **2.6** Run pytest and observe the failing state (no `main.py` yet):
  ```bash
  uv run pytest apps/api/tests/test_health.py -q
  ```
  expected:
  ```
  ImportError while importing test module ... ModuleNotFoundError: No module named 'suitest_api.main'
  ```

- [ ] **2.7** Implement `apps/api/src/suitest_api/main.py`:
  ```python
  """FastAPI application factory."""

  from collections.abc import AsyncIterator
  from contextlib import asynccontextmanager

  from fastapi import FastAPI

  from suitest_api import __version__
  from suitest_api.settings import Settings, get_settings


  @asynccontextmanager
  async def lifespan(app: FastAPI) -> AsyncIterator[None]:
      """Application startup / shutdown hooks (no-op for M0)."""
      app.state.settings = get_settings()
      yield


  def create_app(settings: Settings | None = None) -> FastAPI:
      """Construct the FastAPI app. Pure factory — no side effects at import."""
      app = FastAPI(
          title="Suitest API",
          version=__version__,
          docs_url="/docs",
          redoc_url=None,
          lifespan=lifespan,
      )
      if settings is not None:
          app.state.settings = settings

      @app.get("/health", tags=["meta"])
      async def health() -> dict[str, str]:
          """Liveness probe — no DB / Redis touch."""
          return {"status": "ok", "service": "api", "version": __version__}

      return app


  app = create_app()
  ```

- [ ] **2.8** Create `apps/api/src/suitest_api/__main__.py`:
  ```python
  """`python -m suitest_api` entrypoint — runs uvicorn directly."""

  import uvicorn

  from suitest_api.settings import get_settings


  def main() -> None:
      """Boot uvicorn with the FastAPI app."""
      settings = get_settings()
      uvicorn.run(
          "suitest_api.main:app",
          host=settings.api_host,
          port=settings.api_port,
          log_level=settings.log_level.lower(),
          reload=False,
      )


  if __name__ == "__main__":
      main()
  ```

- [ ] **2.9** Re-run pytest — expect PASS:
  ```bash
  uv sync
  uv run pytest apps/api/tests/test_health.py -q
  ```
  expected:
  ```
  1 passed in 0.XXs
  ```

- [ ] **2.10** Manual smoke (optional but recommended):
  ```bash
  uv run python -m suitest_api &
  sleep 2
  curl -s http://localhost:4000/health
  kill %1
  ```
  expected:
  ```
  {"status":"ok","service":"api","version":"0.1.0"}
  ```

- [ ] **2.11** Commit:
  ```bash
  git add -A
  git commit -m "feat(api): add FastAPI app factory + /health endpoint"
  ```

---

## Task 3: Capability resolver stub + `/capabilities` endpoint (TDD)

**Acceptance criterion:** M0-4 (`GET /capabilities` returns ZERO tier by default).

- [ ] **3.1** Create `packages/core/pyproject.toml`:
  ```toml
  [project]
  name = "suitest-core"
  version = "0.1.0"
  description = "Suitest shared domain logic — capability resolver, autonomy, crypto"
  requires-python = ">=3.12,<3.13"
  dependencies = [
    "pydantic>=2.9.0",
  ]

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/suitest_core"]
  ```

- [ ] **3.2** Create `packages/core/src/suitest_core/__init__.py`:
  ```python
  """Suitest core domain primitives (no IO)."""

  __version__ = "0.1.0"
  ```

- [ ] **3.3** TDD — write failing test first. Create `packages/core/tests/__init__.py` (empty) and `packages/core/tests/test_capabilities.py`:
  ```python
  """Capability tier resolver tests."""

  import pytest

  from suitest_core.capabilities import (
      AutonomyLevel,
      CapabilitySnapshot,
      Tier,
      resolve_capabilities,
      resolve_tier,
  )


  def test_resolve_tier_defaults_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
      """Unset env → ZERO tier."""
      monkeypatch.delenv("SUITEST_LLM_PROVIDER", raising=False)
      assert resolve_tier() is Tier.ZERO


  def test_resolve_tier_explicit_none(monkeypatch: pytest.MonkeyPatch) -> None:
      """`none` literal → ZERO tier."""
      monkeypatch.setenv("SUITEST_LLM_PROVIDER", "none")
      assert resolve_tier() is Tier.ZERO


  def test_resolve_tier_ollama_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
      """`ollama` → LOCAL tier."""
      monkeypatch.setenv("SUITEST_LLM_PROVIDER", "ollama")
      assert resolve_tier() is Tier.LOCAL


  def test_resolve_tier_anthropic_is_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
      """`anthropic` → CLOUD tier."""
      monkeypatch.setenv("SUITEST_LLM_PROVIDER", "anthropic")
      assert resolve_tier() is Tier.CLOUD


  def test_resolve_capabilities_zero_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
      """ZERO snapshot has AI features OFF and autonomy=['manual']."""
      monkeypatch.delenv("SUITEST_LLM_PROVIDER", raising=False)
      snap = resolve_capabilities()
      assert snap.tier is Tier.ZERO
      assert snap.llm_provider is None
      assert snap.features["ai_generation"] is False
      assert snap.features["manual_tcm"] is True
      assert snap.autonomy_available == [AutonomyLevel.MANUAL]
      assert snap.autonomy_default is AutonomyLevel.MANUAL


  def test_capability_snapshot_serialises(monkeypatch: pytest.MonkeyPatch) -> None:
      """Pydantic snapshot can be model_dump()'d."""
      monkeypatch.delenv("SUITEST_LLM_PROVIDER", raising=False)
      snap = resolve_capabilities()
      payload = snap.model_dump(mode="json")
      assert payload["tier"] == "ZERO"
      assert payload["autonomy"]["default"] == "manual"
  ```

- [ ] **3.4** Run pytest to confirm failure (module does not exist):
  ```bash
  uv run pytest packages/core/tests/test_capabilities.py -q
  ```
  expected:
  ```
  ModuleNotFoundError: No module named 'suitest_core.capabilities'
  ```

- [ ] **3.5** Implement `packages/core/src/suitest_core/capabilities.py`:
  ```python
  """Capability tier + autonomy resolver.

  Reads env once at call time. Callers should cache the resulting snapshot for the
  lifetime of the process. See docs/CAPABILITY_TIERS.md for the contract.
  """

  from __future__ import annotations

  import os
  from enum import StrEnum
  from typing import Final

  from pydantic import BaseModel, Field

  LOCAL_PROVIDERS: Final[frozenset[str]] = frozenset({"ollama", "llamacpp", "vllm", "lmstudio"})
  CLOUD_PROVIDERS: Final[frozenset[str]] = frozenset(
      {
          "anthropic",
          "openai",
          "gemini",
          "groq",
          "openrouter",
          "azure",
          "bedrock",
          "vertex",
          "deepseek",
      }
  )
  ZERO_SENTINELS: Final[frozenset[str]] = frozenset({"", "none", "disabled"})


  class Tier(StrEnum):
      """Capability tier resolved from env."""

      ZERO = "ZERO"
      LOCAL = "LOCAL"
      CLOUD = "CLOUD"


  class AutonomyLevel(StrEnum):
      """Workspace autonomy dial. ZERO tier is locked to MANUAL."""

      MANUAL = "manual"
      ASSIST = "assist"
      SEMI_AUTO = "semi_auto"
      AUTO = "auto"


  class LLMInfo(BaseModel):
      """LLM provider info exposed via /capabilities."""

      provider: str | None = None
      model: str | None = None
      base_url: str | None = None


  class EmbeddingsInfo(BaseModel):
      """Embeddings backend info exposed via /capabilities."""

      enabled: bool = False
      backend: str = "none"
      model: str | None = None
      dim: int | None = None


  class AutonomyInfo(BaseModel):
      """Autonomy availability + default for current tier."""

      available: list[AutonomyLevel]
      default: AutonomyLevel


  class CapabilitySnapshot(BaseModel):
      """Immutable view of resolved capabilities."""

      tier: Tier
      llm: LLMInfo = Field(default_factory=LLMInfo)
      llm_provider: str | None = None
      embeddings: EmbeddingsInfo = Field(default_factory=EmbeddingsInfo)
      features: dict[str, bool]
      autonomy: AutonomyInfo
      autonomy_available: list[AutonomyLevel]
      autonomy_default: AutonomyLevel
      version: str = "0.1.0"


  def _read_provider() -> str:
      raw = os.getenv("SUITEST_LLM_PROVIDER") or ""
      return raw.strip().lower()


  def resolve_tier() -> Tier:
      """Pure function: env → Tier. Does not raise for missing keys at M0 (relaxed).

      M0 does NOT validate `SUITEST_LLM_API_KEY` or `SUITEST_LLM_BASE_URL` presence —
      that validation lands in M3 when LiteLLM wiring goes live. This stub only
      maps provider strings to tiers.
      """
      provider = _read_provider()
      if provider in ZERO_SENTINELS:
          return Tier.ZERO
      if provider in LOCAL_PROVIDERS:
          return Tier.LOCAL
      if provider in CLOUD_PROVIDERS:
          return Tier.CLOUD
      # Unknown provider in M0 → treat as ZERO + log; strict validation comes in M3.
      return Tier.ZERO


  def _features_for(tier: Tier) -> dict[str, bool]:
      ai_on = tier is not Tier.ZERO
      return {
          "manual_tcm": True,
          "deterministic_runner": True,
          "deterministic_generator_openapi": True,
          "deterministic_generator_recorder": True,
          "deterministic_generator_crawler": True,
          "ai_generation": ai_on,
          "ai_execution_agentic": ai_on,
          "ai_diagnose": ai_on,
          "ai_conversation": ai_on,
          "semantic_search": False,  # depends on embeddings backend, see M4
          "fts_search": True,
          "auto_defect_filing_ai": ai_on,
          "auto_defect_filing_rule": True,
      }


  def _autonomy_for(tier: Tier) -> AutonomyInfo:
      if tier is Tier.ZERO:
          return AutonomyInfo(available=[AutonomyLevel.MANUAL], default=AutonomyLevel.MANUAL)
      return AutonomyInfo(
          available=[
              AutonomyLevel.MANUAL,
              AutonomyLevel.ASSIST,
              AutonomyLevel.SEMI_AUTO,
              AutonomyLevel.AUTO,
          ],
          default=AutonomyLevel.ASSIST,
      )


  def resolve_capabilities() -> CapabilitySnapshot:
      """Return a fully-populated CapabilitySnapshot from current env."""
      tier = resolve_tier()
      provider = _read_provider()
      llm = LLMInfo(
          provider=provider if tier is not Tier.ZERO else None,
          model=os.getenv("SUITEST_LLM_MODEL") or None,
          base_url=os.getenv("SUITEST_LLM_BASE_URL") or None,
      )
      autonomy = _autonomy_for(tier)
      return CapabilitySnapshot(
          tier=tier,
          llm=llm,
          llm_provider=llm.provider,
          embeddings=EmbeddingsInfo(),
          features=_features_for(tier),
          autonomy=autonomy,
          autonomy_available=autonomy.available,
          autonomy_default=autonomy.default,
      )
  ```

- [ ] **3.6** Re-run pytest and confirm green:
  ```bash
  uv sync
  uv run pytest packages/core/tests/test_capabilities.py -q
  ```
  expected:
  ```
  6 passed in 0.XXs
  ```

- [ ] **3.7** TDD — extend api test suite. Create `apps/api/tests/test_capabilities.py`:
  ```python
  """Contract test for the /capabilities endpoint."""

  import pytest
  from httpx import AsyncClient


  @pytest.mark.asyncio
  async def test_capabilities_zero_default(
      client: AsyncClient, monkeypatch: pytest.MonkeyPatch
  ) -> None:
      """Unset SUITEST_LLM_PROVIDER → ZERO tier capabilities response."""
      monkeypatch.delenv("SUITEST_LLM_PROVIDER", raising=False)
      response = await client.get("/capabilities")
      assert response.status_code == 200
      data = response.json()
      assert data["tier"] == "ZERO"
      assert data["llm_provider"] is None
      assert data["features"]["manual_tcm"] is True
      assert data["features"]["ai_generation"] is False
      assert data["autonomy"]["default"] == "manual"
      assert data["autonomy"]["available"] == ["manual"]
  ```

- [ ] **3.8** Run — expect 404 because the route is not wired yet:
  ```bash
  uv run pytest apps/api/tests/test_capabilities.py -q
  ```
  expected (failure):
  ```
  assert 404 == 200
  ```

- [ ] **3.9** Wire the router. Create `apps/api/src/suitest_api/routers/__init__.py` (empty file) and `apps/api/src/suitest_api/routers/capabilities.py`:
  ```python
  """/capabilities — public, no auth required."""

  from fastapi import APIRouter

  from suitest_core.capabilities import CapabilitySnapshot, resolve_capabilities

  router = APIRouter(tags=["meta"])


  @router.get("/capabilities", response_model=CapabilitySnapshot)
  async def get_capabilities() -> CapabilitySnapshot:
      """Return the resolved capability snapshot. Resolves env fresh on each call.

      M0: env-only resolution. M3 will overlay workspace LLMConfig.
      """
      return resolve_capabilities()
  ```

- [ ] **3.10** Edit `apps/api/src/suitest_api/main.py` to mount the router. Replace the `create_app` function body (everything between the `def create_app(...)` line and the trailing `return app`) so the new include lives next to `/health`:
  ```python
  def create_app(settings: Settings | None = None) -> FastAPI:
      """Construct the FastAPI app. Pure factory — no side effects at import."""
      from suitest_api.routers.capabilities import router as capabilities_router

      app = FastAPI(
          title="Suitest API",
          version=__version__,
          docs_url="/docs",
          redoc_url=None,
          lifespan=lifespan,
      )
      if settings is not None:
          app.state.settings = settings

      @app.get("/health", tags=["meta"])
      async def health() -> dict[str, str]:
          """Liveness probe — no DB / Redis touch."""
          return {"status": "ok", "service": "api", "version": __version__}

      app.include_router(capabilities_router)
      return app
  ```

- [ ] **3.11** Re-run pytest — both health + capabilities should pass:
  ```bash
  uv run pytest apps/api/tests -q
  ```
  expected:
  ```
  2 passed in 0.XXs
  ```

- [ ] **3.12** Commit:
  ```bash
  git add -A
  git commit -m "feat(api): add capability resolver stub + GET /capabilities (ZERO default)"
  ```

---

## Task 4: apps/web Vite + React 19 hello + capability fetch

**Acceptance criterion:** M0-3 (Vite + React 19 + shadcn + Tailwind 4 + Geist).

- [ ] **4.1** Create `apps/web/package.json`:
  ```json
  {
    "name": "@suitest/web",
    "version": "0.1.0",
    "private": true,
    "type": "module",
    "scripts": {
      "dev": "vite",
      "build": "tsc --noEmit && vite build",
      "preview": "vite preview --port 3000",
      "typecheck": "tsc --noEmit",
      "lint": "eslint . --max-warnings=0",
      "format": "prettier --write .",
      "test": "vitest run",
      "test:watch": "vitest"
    },
    "dependencies": {
      "@tanstack/react-query": "^5.59.0",
      "@tanstack/react-router": "^1.79.0",
      "axios": "^1.7.7",
      "clsx": "^2.1.1",
      "react": "^19.0.0",
      "react-dom": "^19.0.0",
      "tailwind-merge": "^2.5.4",
      "zustand": "^5.0.1"
    },
    "devDependencies": {
      "@tailwindcss/vite": "^4.0.0-beta.4",
      "@testing-library/jest-dom": "^6.6.3",
      "@testing-library/react": "^16.0.1",
      "@types/node": "^22.9.0",
      "@types/react": "^19.0.0",
      "@types/react-dom": "^19.0.0",
      "@typescript-eslint/eslint-plugin": "^8.13.0",
      "@typescript-eslint/parser": "^8.13.0",
      "@vitejs/plugin-react": "^4.3.3",
      "eslint": "^9.14.0",
      "eslint-config-prettier": "^9.1.0",
      "eslint-plugin-react": "^7.37.2",
      "eslint-plugin-react-hooks": "^5.0.0",
      "eslint-plugin-react-refresh": "^0.4.14",
      "jsdom": "^25.0.1",
      "prettier": "^3.3.3",
      "tailwindcss": "^4.0.0-beta.4",
      "typescript": "^5.6.3",
      "vite": "^6.0.1",
      "vitest": "^2.1.5"
    }
  }
  ```

- [ ] **4.2** Create `apps/web/vite.config.ts`:
  ```ts
  import { defineConfig } from "vite";
  import react from "@vitejs/plugin-react";
  import tailwindcss from "@tailwindcss/vite";
  import path from "node:path";

  export default defineConfig({
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { "@": path.resolve(__dirname, "./src") },
    },
    server: {
      port: 3000,
      host: "0.0.0.0",
      strictPort: true,
    },
    preview: { port: 3000 },
    build: {
      outDir: "dist",
      sourcemap: true,
      target: "es2022",
    },
  });
  ```

- [ ] **4.3** Create `apps/web/vitest.config.ts`:
  ```ts
  import { defineConfig } from "vitest/config";
  import path from "node:path";

  export default defineConfig({
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test-setup.ts"],
      include: ["src/**/*.{test,spec}.{ts,tsx}"],
    },
    resolve: {
      alias: { "@": path.resolve(__dirname, "./src") },
    },
  });
  ```

- [ ] **4.4** Create `apps/web/src/test-setup.ts`:
  ```ts
  import "@testing-library/jest-dom/vitest";
  ```

- [ ] **4.5** Create `apps/web/index.html`:
  ```html
  <!doctype html>
  <html lang="en" class="dark">
    <head>
      <meta charset="UTF-8" />
      <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <meta name="theme-color" content="#0a0a0a" />
      <title>Suitest</title>
    </head>
    <body class="bg-base text-fg-1 antialiased">
      <div id="root"></div>
      <script type="module" src="/src/main.tsx"></script>
    </body>
  </html>
  ```

- [ ] **4.6** Create `apps/web/public/favicon.svg`:
  ```svg
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
    <rect width="32" height="32" rx="6" fill="#0a0a0a"/>
    <path d="M9 11h14v3H9zM9 17h10v3H9z" fill="#4ade80"/>
  </svg>
  ```

- [ ] **4.7** Create `apps/web/src/styles/globals.css` — Tailwind 4 + Geist + design tokens from CLAUDE.md §3.3:
  ```css
  @import "tailwindcss";

  @font-face {
    font-family: "Geist Sans";
    font-style: normal;
    font-weight: 100 900;
    font-display: swap;
    src: url("/fonts/Geist[wght].woff2") format("woff2-variations");
  }

  @font-face {
    font-family: "Geist Mono";
    font-style: normal;
    font-weight: 100 900;
    font-display: swap;
    src: url("/fonts/GeistMono[wght].woff2") format("woff2-variations");
  }

  @theme {
    --color-base: #0a0a0a;
    --color-elev-1: #111111;
    --color-elev-2: #161616;
    --color-border: #262626;
    --color-fg-1: #fafafa;
    --color-fg-3: #a3a3a3;
    --color-fg-4: #737373;
    --color-accent: #4ade80;
    --color-red: #f87171;
    --color-amber: #fbbf24;
    --color-violet: #a78bfa;
    --font-sans: "Geist Sans", ui-sans-serif, system-ui, sans-serif;
    --font-mono: "Geist Mono", ui-monospace, "JetBrains Mono", monospace;
  }

  html,
  body,
  #root {
    height: 100%;
  }

  body {
    font-family: var(--font-sans);
  }
  ```

- [ ] **4.8** Create `apps/web/src/lib/api-client.ts`:
  ```ts
  import axios, { type AxiosInstance } from "axios";

  const baseURL = import.meta.env["VITE_API_URL"] ?? "http://localhost:4000";

  export const apiClient: AxiosInstance = axios.create({
    baseURL,
    withCredentials: true,
    timeout: 10_000,
    headers: { "Content-Type": "application/json" },
  });
  ```

- [ ] **4.9** Create `apps/web/src/lib/utils.ts`:
  ```ts
  import { clsx, type ClassValue } from "clsx";
  import { twMerge } from "tailwind-merge";

  export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs));
  }
  ```

- [ ] **4.10** Create the capability schema + store at `apps/web/src/stores/use-capabilities.ts`:
  ```ts
  import { create } from "zustand";

  import { apiClient } from "@/lib/api-client";

  export type Tier = "ZERO" | "LOCAL" | "CLOUD";
  export type AutonomyLevel = "manual" | "assist" | "semi_auto" | "auto";

  export interface Capabilities {
    tier: Tier;
    llm_provider: string | null;
    llm: { provider: string | null; model: string | null; base_url: string | null };
    embeddings: { enabled: boolean; backend: string; model: string | null; dim: number | null };
    features: Record<string, boolean>;
    autonomy: { available: AutonomyLevel[]; default: AutonomyLevel };
    version: string;
  }

  interface CapabilitiesState {
    data: Capabilities | null;
    isLoading: boolean;
    error: string | null;
    fetch: () => Promise<void>;
  }

  export const useCapabilities = create<CapabilitiesState>((set) => ({
    data: null,
    isLoading: false,
    error: null,
    fetch: async () => {
      set({ isLoading: true, error: null });
      try {
        const response = await apiClient.get<Capabilities>("/capabilities");
        set({ data: response.data, isLoading: false });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to load capabilities";
        set({ error: message, isLoading: false });
      }
    },
  }));
  ```

- [ ] **4.11** Create `apps/web/src/components/tier-badge.tsx`:
  ```tsx
  import { cn } from "@/lib/utils";
  import { useCapabilities } from "@/stores/use-capabilities";

  export function TierBadge(): React.ReactElement {
    const data = useCapabilities((s) => s.data);
    const tier = data?.tier ?? "ZERO";
    const provider = data?.llm_provider;

    const tone = {
      ZERO: "bg-elev-2 text-fg-3 border-border",
      LOCAL: "bg-elev-2 text-accent border-accent/40",
      CLOUD: "bg-elev-2 text-violet border-violet/40",
    }[tier];

    return (
      <span
        className={cn(
          "inline-flex items-center gap-2 rounded-md border px-2 py-1 font-mono text-xs",
          tone,
        )}
        data-testid="tier-badge"
      >
        <span className="font-semibold">{tier}</span>
        {provider ? <span className="text-fg-4">· {provider}</span> : null}
      </span>
    );
  }
  ```

- [ ] **4.12** Create `apps/web/src/routes/__root.tsx`:
  ```tsx
  import { Outlet, createRootRoute } from "@tanstack/react-router";
  import { useEffect } from "react";

  import { TierBadge } from "@/components/tier-badge";
  import { useCapabilities } from "@/stores/use-capabilities";

  function RootLayout(): React.ReactElement {
    const fetch = useCapabilities((s) => s.fetch);
    useEffect(() => {
      void fetch();
    }, [fetch]);

    return (
      <div className="flex min-h-full flex-col">
        <header className="flex items-center justify-between border-b border-border px-6 py-3">
          <h1 className="font-mono text-lg font-semibold tracking-tight">Suitest</h1>
          <TierBadge />
        </header>
        <main className="flex-1 px-6 py-8">
          <Outlet />
        </main>
      </div>
    );
  }

  export const Route = createRootRoute({ component: RootLayout });
  ```

- [ ] **4.13** Create `apps/web/src/routes/index.tsx`:
  ```tsx
  import { createFileRoute } from "@tanstack/react-router";

  import { useCapabilities } from "@/stores/use-capabilities";

  function Home(): React.ReactElement {
    const { data, isLoading, error } = useCapabilities();
    if (isLoading) return <p className="text-fg-3">Loading capabilities…</p>;
    if (error) return <p className="text-red">Error: {error}</p>;
    if (!data) return <p className="text-fg-4">Awaiting capabilities…</p>;
    return (
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">Welcome to Suitest</h2>
        <p className="text-fg-3">
          Running in <span className="font-mono text-fg-1">{data.tier}</span> tier.
        </p>
      </section>
    );
  }

  export const Route = createFileRoute("/")({ component: Home });
  ```

- [ ] **4.14** Create `apps/web/src/routeTree.gen.ts` placeholder (route tree generated at dev time; for M0 we hand-write the minimum):
  ```ts
  /* eslint-disable */
  // Hand-written for M0 — TanStack Router CLI will replace this in M1.
  import { Route as RootRoute } from "./routes/__root";
  import { Route as IndexRoute } from "./routes/index";

  declare module "@tanstack/react-router" {
    interface FileRoutesByPath {
      "/": { parentRoute: typeof RootRoute };
    }
  }

  const IndexRouteWithChildren = IndexRoute.update({
    id: "/",
    path: "/",
    getParentRoute: () => RootRoute,
  });

  export const routeTree = RootRoute.addChildren([IndexRouteWithChildren]);
  ```

- [ ] **4.15** Create `apps/web/src/main.tsx`:
  ```tsx
  import { RouterProvider, createRouter } from "@tanstack/react-router";
  import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
  import { StrictMode } from "react";
  import { createRoot } from "react-dom/client";

  import { routeTree } from "./routeTree.gen";
  import "./styles/globals.css";

  const router = createRouter({ routeTree, defaultPreload: "intent" });

  declare module "@tanstack/react-router" {
    interface Register {
      router: typeof router;
    }
  }

  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
  });

  const rootEl = document.getElementById("root");
  if (!rootEl) throw new Error("#root element missing in index.html");

  createRoot(rootEl).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
  ```

- [ ] **4.16** Vitest — capability store fetches + stores response. Create `apps/web/src/stores/use-capabilities.test.ts`:
  ```ts
  import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

  import { apiClient } from "@/lib/api-client";
  import { useCapabilities } from "@/stores/use-capabilities";

  describe("useCapabilities", () => {
    beforeEach(() => {
      useCapabilities.setState({ data: null, isLoading: false, error: null });
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("populates store with ZERO tier payload on success", async () => {
      const payload = {
        tier: "ZERO" as const,
        llm_provider: null,
        llm: { provider: null, model: null, base_url: null },
        embeddings: { enabled: false, backend: "none", model: null, dim: null },
        features: { manual_tcm: true, ai_generation: false },
        autonomy: { available: ["manual" as const], default: "manual" as const },
        version: "0.1.0",
      };
      vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: payload } as never);

      await useCapabilities.getState().fetch();

      const state = useCapabilities.getState();
      expect(state.isLoading).toBe(false);
      expect(state.error).toBeNull();
      expect(state.data?.tier).toBe("ZERO");
      expect(state.data?.features["ai_generation"]).toBe(false);
    });

    it("records error message on failure", async () => {
      vi.spyOn(apiClient, "get").mockRejectedValueOnce(new Error("network down"));

      await useCapabilities.getState().fetch();

      const state = useCapabilities.getState();
      expect(state.data).toBeNull();
      expect(state.error).toBe("network down");
    });
  });
  ```

- [ ] **4.17** Install + run:
  ```bash
  cd apps/web
  pnpm install
  pnpm test
  pnpm typecheck
  ```
  expected:
  ```
  Test Files  1 passed (1)
       Tests  2 passed (2)
  ```

- [ ] **4.18** Smoke (optional): boot api in one terminal + `pnpm dev` in another, visit `http://localhost:3000` — see "Welcome to Suitest" + `ZERO` badge top-right.

- [ ] **4.19** Commit:
  ```bash
  cd ../..
  git add -A
  git commit -m "feat(web): bootstrap Vite + React 19 SPA with tier badge + capability store"
  ```

---

## Task 5: docker-compose for postgres + redis + minio

**Acceptance criterion:** M0-5 (compose with pg+pgvector, redis, minio).

- [ ] **5.1** Create `infra/docker/docker-compose.yml`:
  ```yaml
  name: suitest

  x-suitest-env: &suitest-env
    SUITEST_DATABASE_URL: ${SUITEST_DATABASE_URL}
    SUITEST_REDIS_URL: ${SUITEST_REDIS_URL}
    SUITEST_S3_ENDPOINT: ${SUITEST_S3_ENDPOINT}
    SUITEST_S3_BUCKET: ${SUITEST_S3_BUCKET}
    SUITEST_S3_ACCESS_KEY: ${SUITEST_S3_ACCESS_KEY}
    SUITEST_S3_SECRET_KEY: ${SUITEST_S3_SECRET_KEY}
    SUITEST_LLM_PROVIDER: ${SUITEST_LLM_PROVIDER:-}
    SUITEST_ENCRYPTION_KEY: ${SUITEST_ENCRYPTION_KEY}
    SUITEST_AUTH_SECRET: ${SUITEST_AUTH_SECRET}
    SUITEST_WEB_URL: ${SUITEST_WEB_URL}
    SUITEST_API_URL: ${SUITEST_API_URL}
    SUITEST_OAUTH_GOOGLE_CLIENT_ID: ${SUITEST_OAUTH_GOOGLE_CLIENT_ID:-}
    SUITEST_OAUTH_GOOGLE_CLIENT_SECRET: ${SUITEST_OAUTH_GOOGLE_CLIENT_SECRET:-}

  services:
    postgres:
      image: pgvector/pgvector:pg16
      profiles: ["zero", "cloud", "local", "dev"]
      restart: unless-stopped
      environment:
        POSTGRES_USER: suitest
        POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-suitest}
        POSTGRES_DB: suitest
      ports:
        - "5432:5432"
      volumes:
        - pgdata:/var/lib/postgresql/data
      healthcheck:
        test: ["CMD-SHELL", "pg_isready -U suitest -d suitest"]
        interval: 5s
        timeout: 5s
        retries: 10

    redis:
      image: redis:7-alpine
      profiles: ["zero", "cloud", "local", "dev"]
      restart: unless-stopped
      command: ["redis-server", "--appendonly", "yes"]
      ports:
        - "6379:6379"
      volumes:
        - redisdata:/data
      healthcheck:
        test: ["CMD", "redis-cli", "ping"]
        interval: 5s
        timeout: 3s
        retries: 10

    minio:
      image: minio/minio:latest
      profiles: ["zero", "cloud", "local", "dev"]
      restart: unless-stopped
      command: ["server", "/data", "--console-address", ":9001"]
      environment:
        MINIO_ROOT_USER: ${SUITEST_S3_ACCESS_KEY:-minioadmin}
        MINIO_ROOT_PASSWORD: ${SUITEST_S3_SECRET_KEY:-minioadmin}
      ports:
        - "9000:9000"
        - "9001:9001"
      volumes:
        - miniodata:/data
      healthcheck:
        test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/ready"]
        interval: 10s
        timeout: 5s
        retries: 10

    minio-init:
      image: minio/mc:latest
      profiles: ["zero", "cloud", "local", "dev"]
      depends_on:
        minio:
          condition: service_healthy
      entrypoint: >
        /bin/sh -c "
          mc alias set local http://minio:9000 ${SUITEST_S3_ACCESS_KEY:-minioadmin} ${SUITEST_S3_SECRET_KEY:-minioadmin} &&
          mc mb --ignore-existing local/${SUITEST_S3_BUCKET:-suitest-artifacts} &&
          mc anonymous set download local/${SUITEST_S3_BUCKET:-suitest-artifacts} ||
          echo 'bucket init done';
        "
      restart: "no"

  volumes:
    pgdata:
    redisdata:
    miniodata:

  networks:
    default:
      name: suitest
  ```

- [ ] **5.2** Create root `.env.example`:
  ```env
  # === Required ===
  POSTGRES_PASSWORD=suitest
  SUITEST_AUTH_SECRET=replace-with-32-char-random-hex
  SUITEST_ENCRYPTION_KEY=replace-with-base64-32-byte-key

  # === Database / queue / storage ===
  SUITEST_DATABASE_URL=postgresql+asyncpg://suitest:suitest@postgres:5432/suitest
  SUITEST_REDIS_URL=redis://redis:6379/0
  SUITEST_S3_ENDPOINT=http://minio:9000
  SUITEST_S3_BUCKET=suitest-artifacts
  SUITEST_S3_ACCESS_KEY=minioadmin
  SUITEST_S3_SECRET_KEY=minioadmin

  # === URLs ===
  SUITEST_WEB_URL=http://localhost:3000
  SUITEST_API_URL=http://localhost:4000

  # === Tier dial (ZERO default) ===
  SUITEST_LLM_PROVIDER=
  SUITEST_LLM_API_KEY=
  SUITEST_LLM_MODEL=
  SUITEST_LLM_BASE_URL=
  SUITEST_EMBEDDINGS_BACKEND=none

  # === OAuth (optional, required for login flow in Task 7) ===
  SUITEST_OAUTH_GOOGLE_CLIENT_ID=
  SUITEST_OAUTH_GOOGLE_CLIENT_SECRET=

  # === To upgrade to CLOUD (uncomment) ===
  # SUITEST_LLM_PROVIDER=anthropic
  # SUITEST_LLM_API_KEY=sk-ant-...
  # SUITEST_LLM_MODEL=claude-sonnet-4-5
  ```

- [ ] **5.3** Manual verify:
  ```bash
  cp .env.example .env
  # generate proper secrets
  python -c "import secrets; print('SUITEST_AUTH_SECRET=' + secrets.token_hex(32))"
  python -c "import secrets,base64; print('SUITEST_ENCRYPTION_KEY=' + base64.b64encode(secrets.token_bytes(32)).decode())"
  # paste those into .env, then:
  docker compose -f infra/docker/docker-compose.yml --env-file .env --profile zero up -d
  sleep 10
  docker compose -f infra/docker/docker-compose.yml ps
  ```
  expected: all three services show status `Up (healthy)` and `minio-init` shows `Exited (0)`.

- [ ] **5.4** Tear down to keep working tree clean:
  ```bash
  docker compose -f infra/docker/docker-compose.yml down
  ```
  expected:
  ```
  [+] Running 4/4
   ✔ Container suitest-minio-init-1 Removed
   ✔ Container suitest-minio-1      Removed
   ✔ Container suitest-redis-1      Removed
   ✔ Container suitest-postgres-1   Removed
  ```

- [ ] **5.5** Commit:
  ```bash
  git add -A
  git commit -m "feat(infra): add docker-compose for postgres+pgvector, redis, minio"
  ```

---

## Task 6: SQLAlchemy 2 async + Alembic init migration (TDD)

**Acceptance criterion:** M0-6 (SQLAlchemy 2 async + Alembic init migration applied).

- [ ] **6.1** Create `packages/db/pyproject.toml`:
  ```toml
  [project]
  name = "suitest-db"
  version = "0.1.0"
  description = "Suitest async DB layer (SQLAlchemy 2 + Alembic + repositories)"
  requires-python = ">=3.12,<3.13"
  dependencies = [
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30.0",
    "alembic>=1.14.0",
    "cuid2>=2.0.1",
    "pydantic>=2.9.0",
    "suitest-core",
  ]

  [project.optional-dependencies]
  test = [
    "testcontainers[postgres]>=4.8.0",
  ]

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/suitest_db"]
  ```

- [ ] **6.2** Create `packages/db/src/suitest_db/__init__.py`:
  ```python
  """Suitest async DB layer."""

  __version__ = "0.1.0"
  ```

- [ ] **6.3** Create `packages/db/src/suitest_db/settings.py`:
  ```python
  """DB-scoped settings."""

  from pydantic import Field
  from pydantic_settings import BaseSettings, SettingsConfigDict


  class DbSettings(BaseSettings):
      """Database connection config."""

      model_config = SettingsConfigDict(env_prefix="SUITEST_", extra="ignore")

      database_url: str = Field(
          default="postgresql+asyncpg://suitest:suitest@localhost:5432/suitest"
      )
      echo_sql: bool = Field(default=False)
      pool_size: int = Field(default=5)
      max_overflow: int = Field(default=10)
  ```

- [ ] **6.4** Create `packages/db/src/suitest_db/base.py`:
  ```python
  """SQLAlchemy declarative base."""

  from datetime import datetime

  from sqlalchemy import DateTime, MetaData, func
  from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

  NAMING_CONVENTION = {
      "ix": "ix_%(column_0_label)s",
      "uq": "uq_%(table_name)s_%(column_0_name)s",
      "ck": "ck_%(table_name)s_%(constraint_name)s",
      "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
      "pk": "pk_%(table_name)s",
  }


  class Base(DeclarativeBase):
      """Project-wide declarative base with shared metadata + timestamps."""

      metadata = MetaData(naming_convention=NAMING_CONVENTION)


  class TimestampMixin:
      """Mixin: created_at / updated_at managed by Postgres."""

      created_at: Mapped[datetime] = mapped_column(
          DateTime(timezone=True), nullable=False, server_default=func.now()
      )
      updated_at: Mapped[datetime] = mapped_column(
          DateTime(timezone=True),
          nullable=False,
          server_default=func.now(),
          onupdate=func.now(),
      )
  ```

- [ ] **6.5** Create `packages/db/src/suitest_db/engine.py`:
  ```python
  """Async engine + session factory."""

  from collections.abc import AsyncIterator
  from contextlib import asynccontextmanager

  from sqlalchemy.ext.asyncio import (
      AsyncEngine,
      AsyncSession,
      async_sessionmaker,
      create_async_engine,
  )

  from suitest_db.settings import DbSettings


  def make_engine(settings: DbSettings | None = None) -> AsyncEngine:
      """Construct an async engine. Caller owns the lifecycle (dispose())."""
      cfg = settings or DbSettings()
      return create_async_engine(
          cfg.database_url,
          echo=cfg.echo_sql,
          pool_size=cfg.pool_size,
          max_overflow=cfg.max_overflow,
          pool_pre_ping=True,
          future=True,
      )


  def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
      """Bind a session factory to the provided engine."""
      return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


  @asynccontextmanager
  async def lifespan_engine(
      settings: DbSettings | None = None,
  ) -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
      """Async context manager that yields (engine, session_factory) and disposes."""
      engine = make_engine(settings)
      try:
          yield engine, make_session_factory(engine)
      finally:
          await engine.dispose()
  ```

- [ ] **6.6** Create `packages/db/src/suitest_db/ids.py`:
  ```python
  """cuid2-based ID generator helper."""

  from cuid2 import Cuid

  _cuid = Cuid(length=24)


  def new_id() -> str:
      """Return a new 24-char cuid2 string."""
      return _cuid.generate()
  ```

- [ ] **6.7** Create `packages/db/src/suitest_db/models/__init__.py`:
  ```python
  """SQLAlchemy models. Import here to keep Alembic autogenerate happy."""

  from suitest_db.models.workspace import Workspace

  __all__ = ["Workspace"]
  ```

- [ ] **6.8** Create `packages/db/src/suitest_db/models/workspace.py`:
  ```python
  """Workspace model — minimal M0 stub. Full schema lands in M1a (DATA_MODEL.md)."""

  from sqlalchemy import String
  from sqlalchemy.orm import Mapped, mapped_column

  from suitest_db.base import Base, TimestampMixin
  from suitest_db.ids import new_id


  class Workspace(Base, TimestampMixin):
      """Workspace = top-level tenant boundary."""

      __tablename__ = "workspaces"

      id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
      slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
      name: Mapped[str] = mapped_column(String(128), nullable=False)
  ```

- [ ] **6.9** Create `packages/db/alembic.ini`:
  ```ini
  [alembic]
  script_location = alembic
  prepend_sys_path = .
  version_path_separator = os
  sqlalchemy.url = postgresql+asyncpg://suitest:suitest@localhost:5432/suitest
  file_template = %%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d_%%(slug)s

  [post_write_hooks]
  hooks = ruff
  ruff.type = console_scripts
  ruff.entrypoint = ruff
  ruff.options = check --fix REVISION_SCRIPT_FILENAME

  [loggers]
  keys = root,sqlalchemy,alembic

  [handlers]
  keys = console

  [formatters]
  keys = generic

  [logger_root]
  level = WARN
  handlers = console
  qualname =

  [logger_sqlalchemy]
  level = WARN
  handlers =
  qualname = sqlalchemy.engine

  [logger_alembic]
  level = INFO
  handlers =
  qualname = alembic

  [handler_console]
  class = StreamHandler
  args = (sys.stderr,)
  level = NOTSET
  formatter = generic

  [formatter_generic]
  format = %(levelname)-5.5s [%(name)s] %(message)s
  datefmt = %H:%M:%S
  ```

- [ ] **6.10** Create `packages/db/alembic/env.py` (async-aware):
  ```python
  """Alembic env — async engine + import all models for autogenerate."""

  import asyncio
  import os
  from logging.config import fileConfig

  from alembic import context
  from sqlalchemy import pool
  from sqlalchemy.engine import Connection
  from sqlalchemy.ext.asyncio import async_engine_from_config

  from suitest_db.base import Base
  from suitest_db.models import Workspace  # noqa: F401 — keep import for autogenerate

  config = context.config
  if config.config_file_name is not None:
      fileConfig(config.config_file_name)

  target_metadata = Base.metadata


  def _url() -> str:
      env_url = os.getenv("SUITEST_DATABASE_URL")
      if env_url:
          return env_url
      return config.get_main_option("sqlalchemy.url") or ""


  def run_migrations_offline() -> None:
      """Emit SQL to stdout (no DB connection)."""
      context.configure(
          url=_url(),
          target_metadata=target_metadata,
          literal_binds=True,
          dialect_opts={"paramstyle": "named"},
      )
      with context.begin_transaction():
          context.run_migrations()


  def do_run_migrations(connection: Connection) -> None:
      context.configure(connection=connection, target_metadata=target_metadata)
      with context.begin_transaction():
          context.run_migrations()


  async def run_async_migrations() -> None:
      cfg = config.get_section(config.config_ini_section) or {}
      cfg["sqlalchemy.url"] = _url()
      connectable = async_engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
      async with connectable.connect() as connection:
          await connection.run_sync(do_run_migrations)
      await connectable.dispose()


  def run_migrations_online() -> None:
      asyncio.run(run_async_migrations())


  if context.is_offline_mode():
      run_migrations_offline()
  else:
      run_migrations_online()
  ```

- [ ] **6.11** Create `packages/db/alembic/script.py.mako`:
  ```python
  """${message}

  Revision ID: ${up_revision}
  Revises: ${down_revision | comma,n}
  Create Date: ${create_date}

  """
  from collections.abc import Sequence

  from alembic import op
  import sqlalchemy as sa
  ${imports if imports else ""}

  # revision identifiers, used by Alembic.
  revision: str = ${repr(up_revision)}
  down_revision: str | None = ${repr(down_revision)}
  branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
  depends_on: str | Sequence[str] | None = ${repr(depends_on)}


  def upgrade() -> None:
      ${upgrades if upgrades else "pass"}


  def downgrade() -> None:
      ${downgrades if downgrades else "pass"}
  ```

- [ ] **6.12** Create init migration `packages/db/alembic/versions/20260526_0001_init_workspaces.py`:
  ```python
  """init workspaces table

  Revision ID: 0001_init_workspaces
  Revises:
  Create Date: 2026-05-26

  """
  from collections.abc import Sequence

  from alembic import op
  import sqlalchemy as sa

  revision: str = "0001_init_workspaces"
  down_revision: str | None = None
  branch_labels: str | Sequence[str] | None = None
  depends_on: str | Sequence[str] | None = None


  def upgrade() -> None:
      op.execute("CREATE EXTENSION IF NOT EXISTS vector")
      op.create_table(
          "workspaces",
          sa.Column("id", sa.String(length=32), nullable=False),
          sa.Column("slug", sa.String(length=64), nullable=False),
          sa.Column("name", sa.String(length=128), nullable=False),
          sa.Column(
              "created_at",
              sa.DateTime(timezone=True),
              server_default=sa.text("now()"),
              nullable=False,
          ),
          sa.Column(
              "updated_at",
              sa.DateTime(timezone=True),
              server_default=sa.text("now()"),
              nullable=False,
          ),
          sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
          sa.UniqueConstraint("slug", name=op.f("uq_workspaces_slug")),
      )


  def downgrade() -> None:
      op.drop_table("workspaces")
  ```

- [ ] **6.13** Generate-then-verify dance — confirm `alembic check` finds no drift:
  ```bash
  docker compose -f infra/docker/docker-compose.yml --env-file .env --profile zero up -d postgres
  sleep 5
  cd packages/db
  SUITEST_DATABASE_URL=postgresql+asyncpg://suitest:suitest@localhost:5432/suitest \
    uv run alembic upgrade head
  ```
  expected:
  ```
  INFO  [alembic.runtime.migration] Running upgrade  -> 0001_init_workspaces, init workspaces
  ```

- [ ] **6.14** TDD — write engine + migration round-trip test. Create `packages/db/tests/__init__.py` (empty) and `packages/db/tests/test_engine.py`:
  ```python
  """End-to-end: migrate → insert Workspace → query back."""

  from collections.abc import AsyncIterator

  import pytest
  import pytest_asyncio
  from sqlalchemy import select
  from sqlalchemy.ext.asyncio import AsyncSession

  from suitest_db.engine import lifespan_engine
  from suitest_db.models import Workspace
  from suitest_db.settings import DbSettings


  @pytest_asyncio.fixture
  async def session() -> AsyncIterator[AsyncSession]:
      """Yield a session against the local dev Postgres (run after compose up + alembic upgrade)."""
      settings = DbSettings(
          database_url="postgresql+asyncpg://suitest:suitest@localhost:5432/suitest"
      )
      async with lifespan_engine(settings) as (engine, sf):
          async with sf() as s:
              yield s
              await s.rollback()


  @pytest.mark.asyncio
  async def test_workspace_insert_and_query(session: AsyncSession) -> None:
      """Insert a workspace, commit, query back, assert fields."""
      ws = Workspace(slug="test-engine-roundtrip", name="Engine Roundtrip")
      session.add(ws)
      await session.commit()

      stmt = select(Workspace).where(Workspace.slug == "test-engine-roundtrip")
      result = await session.execute(stmt)
      fetched = result.scalar_one()

      assert fetched.id is not None
      assert len(fetched.id) == 24  # cuid2 length
      assert fetched.name == "Engine Roundtrip"
      assert fetched.created_at is not None

      # cleanup
      await session.delete(fetched)
      await session.commit()
  ```

- [ ] **6.15** Run the test:
  ```bash
  cd ../..
  uv sync
  uv run pytest packages/db/tests/test_engine.py -q
  ```
  expected:
  ```
  1 passed in 0.XXs
  ```

- [ ] **6.16** Stop postgres to keep tree clean:
  ```bash
  docker compose -f infra/docker/docker-compose.yml down
  ```

- [ ] **6.17** Commit:
  ```bash
  git add -A
  git commit -m "feat(db): add SQLAlchemy 2 async engine + Alembic init migration (workspaces)"
  ```

---

## Task 7: FastAPI-Users + Google OAuth (TDD)

**Acceptance criterion:** M0-8 (FastAPI-Users with Google OAuth → redirect `/dashboard`).

- [ ] **7.1** Update `apps/api/pyproject.toml` adding auth deps. Replace the `dependencies = [...]` block with:
  ```toml
  dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "structlog>=24.4.0",
    "fastapi-users[sqlalchemy,oauth]>=14.0.0",
    "authlib>=1.3.2",
    "itsdangerous>=2.2.0",
    "httpx-oauth>=0.16.0",
    "suitest-core",
    "suitest-db",
    "suitest-shared",
  ]
  ```

- [ ] **7.2** Add user models. Create `packages/db/src/suitest_db/models/user.py`:
  ```python
  """User + OAuth account models for FastAPI-Users."""

  from fastapi_users.db import SQLAlchemyBaseOAuthAccountTableUUID, SQLAlchemyBaseUserTableUUID
  from sqlalchemy import ForeignKey
  from sqlalchemy.orm import Mapped, mapped_column, relationship

  from suitest_db.base import Base


  class User(SQLAlchemyBaseUserTableUUID, Base):
      """Suitest user. UUID PK as required by FastAPI-Users SQLAlchemy adapter."""

      __tablename__ = "users"

      oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(
          "OAuthAccount", lazy="joined", cascade="all, delete-orphan"
      )


  class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
      """OAuth account linked to a User."""

      __tablename__ = "oauth_accounts"

      user_id: Mapped[str] = mapped_column(
          ForeignKey("users.id", ondelete="CASCADE"), nullable=False
      )
  ```

- [ ] **7.3** Re-export from `packages/db/src/suitest_db/models/__init__.py`:
  ```python
  """SQLAlchemy models. Import here to keep Alembic autogenerate happy."""

  from suitest_db.models.user import OAuthAccount, User
  from suitest_db.models.workspace import Workspace

  __all__ = ["OAuthAccount", "User", "Workspace"]
  ```

- [ ] **7.4** Create migration `packages/db/alembic/versions/20260526_0002_add_users.py`:
  ```python
  """add users + oauth_accounts

  Revision ID: 0002_add_users
  Revises: 0001_init_workspaces
  Create Date: 2026-05-26

  """
  from collections.abc import Sequence

  from alembic import op
  import sqlalchemy as sa
  from fastapi_users_db_sqlalchemy.generics import GUID

  revision: str = "0002_add_users"
  down_revision: str | None = "0001_init_workspaces"
  branch_labels: str | Sequence[str] | None = None
  depends_on: str | Sequence[str] | None = None


  def upgrade() -> None:
      op.create_table(
          "users",
          sa.Column("id", GUID(), nullable=False),
          sa.Column("email", sa.String(length=320), nullable=False),
          sa.Column("hashed_password", sa.String(length=1024), nullable=False),
          sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
          sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
          sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
          sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
          sa.UniqueConstraint("email", name=op.f("uq_users_email")),
      )
      op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

      op.create_table(
          "oauth_accounts",
          sa.Column("id", GUID(), nullable=False),
          sa.Column("user_id", GUID(), nullable=False),
          sa.Column("oauth_name", sa.String(length=100), nullable=False),
          sa.Column("access_token", sa.String(length=1024), nullable=False),
          sa.Column("expires_at", sa.Integer(), nullable=True),
          sa.Column("refresh_token", sa.String(length=1024), nullable=True),
          sa.Column("account_id", sa.String(length=320), nullable=False),
          sa.Column("account_email", sa.String(length=320), nullable=False),
          sa.ForeignKeyConstraint(
              ["user_id"], ["users.id"],
              name=op.f("fk_oauth_accounts_user_id_users"),
              ondelete="CASCADE",
          ),
          sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_accounts")),
      )
      op.create_index(op.f("ix_oauth_accounts_account_id"), "oauth_accounts", ["account_id"])
      op.create_index(op.f("ix_oauth_accounts_oauth_name"), "oauth_accounts", ["oauth_name"])


  def downgrade() -> None:
      op.drop_index(op.f("ix_oauth_accounts_oauth_name"), table_name="oauth_accounts")
      op.drop_index(op.f("ix_oauth_accounts_account_id"), table_name="oauth_accounts")
      op.drop_table("oauth_accounts")
      op.drop_index(op.f("ix_users_email"), table_name="users")
      op.drop_table("users")
  ```

- [ ] **7.5** Auth settings — extend `apps/api/src/suitest_api/settings.py` (append fields to `Settings`):
  ```python
  """Process-level settings sourced from environment."""

  from pydantic import Field
  from pydantic_settings import BaseSettings, SettingsConfigDict


  class Settings(BaseSettings):
      """Top-level config for the API process."""

      model_config = SettingsConfigDict(
          env_prefix="SUITEST_",
          env_file=None,
          extra="ignore",
          case_sensitive=False,
      )

      api_host: str = Field(default="0.0.0.0")
      api_port: int = Field(default=4000)
      web_url: str = Field(default="http://localhost:3000")
      api_url: str = Field(default="http://localhost:4000")
      log_level: str = Field(default="INFO")
      auth_secret: str = Field(default="dev-secret-change-me-32chars-min")
      database_url: str = Field(
          default="postgresql+asyncpg://suitest:suitest@localhost:5432/suitest"
      )
      oauth_google_client_id: str = Field(default="")
      oauth_google_client_secret: str = Field(default="")


  def get_settings() -> Settings:
      """Return a fresh Settings instance (env-resolved)."""
      return Settings()
  ```

- [ ] **7.6** Create auth module. `apps/api/src/suitest_api/auth/__init__.py` (empty file).

- [ ] **7.7** Create `apps/api/src/suitest_api/auth/db.py`:
  ```python
  """SQLAlchemy session + user-db adapter for FastAPI-Users."""

  from collections.abc import AsyncIterator

  from fastapi import Depends
  from fastapi_users.db import SQLAlchemyUserDatabase
  from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

  from suitest_api.settings import get_settings
  from suitest_db.engine import make_engine, make_session_factory
  from suitest_db.models import OAuthAccount, User
  from suitest_db.settings import DbSettings

  _engine = make_engine(DbSettings(database_url=get_settings().database_url))
  _session_factory: async_sessionmaker[AsyncSession] = make_session_factory(_engine)


  async def get_async_session() -> AsyncIterator[AsyncSession]:
      """Yield a fresh AsyncSession per-request."""
      async with _session_factory() as session:
          yield session


  async def get_user_db(
      session: AsyncSession = Depends(get_async_session),
  ) -> AsyncIterator[SQLAlchemyUserDatabase[User, str]]:
      """Adapter that FastAPI-Users uses to read/write User rows."""
      yield SQLAlchemyUserDatabase(session, User, OAuthAccount)
  ```

- [ ] **7.8** Create `apps/api/src/suitest_api/auth/schemas.py`:
  ```python
  """Pydantic schemas for user IO."""

  import uuid

  from fastapi_users import schemas


  class UserRead(schemas.BaseUser[uuid.UUID]):
      """Public user representation."""


  class UserCreate(schemas.BaseUserCreate):
      """Signup payload."""


  class UserUpdate(schemas.BaseUserUpdate):
      """Update payload."""
  ```

- [ ] **7.9** Create `apps/api/src/suitest_api/auth/manager.py`:
  ```python
  """UserManager + dependency wiring for FastAPI-Users."""

  import uuid
  from collections.abc import AsyncIterator

  from fastapi import Depends, Request
  from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
  from fastapi_users.authentication import (
      AuthenticationBackend,
      CookieTransport,
      JWTStrategy,
  )
  from fastapi_users.db import SQLAlchemyUserDatabase

  from suitest_api.auth.db import get_user_db
  from suitest_api.settings import get_settings
  from suitest_db.models import User


  class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
      """Hooks for register / login / verify flows."""

      reset_password_token_secret = get_settings().auth_secret
      verification_token_secret = get_settings().auth_secret

      async def on_after_register(self, user: User, request: Request | None = None) -> None:
          """Optional hook — log new registrations. No side effects in M0."""
          _ = request
          _ = user


  async def get_user_manager(
      user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = Depends(get_user_db),
  ) -> AsyncIterator[UserManager]:
      """FastAPI dependency: yields a UserManager."""
      yield UserManager(user_db)


  cookie_transport = CookieTransport(
      cookie_name="suitest_session",
      cookie_max_age=60 * 60 * 24 * 14,  # 14 days
      cookie_secure=False,  # set True behind HTTPS in production
      cookie_httponly=True,
      cookie_samesite="lax",
  )


  def get_jwt_strategy() -> JWTStrategy[User, uuid.UUID]:
      """JWT strategy keyed off SUITEST_AUTH_SECRET."""
      return JWTStrategy(secret=get_settings().auth_secret, lifetime_seconds=60 * 60 * 24 * 14)


  auth_backend = AuthenticationBackend(
      name="cookie-jwt",
      transport=cookie_transport,
      get_strategy=get_jwt_strategy,
  )

  fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

  current_active_user = fastapi_users.current_user(active=True)
  ```

- [ ] **7.10** Create `apps/api/src/suitest_api/auth/router.py`:
  ```python
  """Wire FastAPI-Users routers + Google OAuth router."""

  from fastapi import APIRouter
  from httpx_oauth.clients.google import GoogleOAuth2

  from suitest_api.auth.manager import auth_backend, fastapi_users
  from suitest_api.auth.schemas import UserCreate, UserRead, UserUpdate
  from suitest_api.settings import get_settings

  _settings = get_settings()

  router = APIRouter()

  router.include_router(
      fastapi_users.get_auth_router(auth_backend),
      prefix="/auth/cookie",
      tags=["auth"],
  )
  router.include_router(
      fastapi_users.get_register_router(UserRead, UserCreate),
      prefix="/auth",
      tags=["auth"],
  )
  router.include_router(
      fastapi_users.get_users_router(UserRead, UserUpdate),
      prefix="/users",
      tags=["users"],
  )


  google_oauth_client = GoogleOAuth2(
      client_id=_settings.oauth_google_client_id or "unset",
      client_secret=_settings.oauth_google_client_secret or "unset",
  )

  router.include_router(
      fastapi_users.get_oauth_router(
          google_oauth_client,
          auth_backend,
          _settings.auth_secret,
          redirect_url=f"{_settings.web_url}/dashboard",
          associate_by_email=True,
          is_verified_by_default=True,
      ),
      prefix="/auth/google",
      tags=["auth"],
  )
  ```

- [ ] **7.11** Wire into `apps/api/src/suitest_api/main.py` — replace the `create_app` body so it includes both routers:
  ```python
  def create_app(settings: Settings | None = None) -> FastAPI:
      """Construct the FastAPI app. Pure factory — no side effects at import."""
      from suitest_api.auth.router import router as auth_router
      from suitest_api.routers.capabilities import router as capabilities_router

      app = FastAPI(
          title="Suitest API",
          version=__version__,
          docs_url="/docs",
          redoc_url=None,
          lifespan=lifespan,
      )
      if settings is not None:
          app.state.settings = settings

      @app.get("/health", tags=["meta"])
      async def health() -> dict[str, str]:
          """Liveness probe — no DB / Redis touch."""
          return {"status": "ok", "service": "api", "version": __version__}

      app.include_router(capabilities_router)
      app.include_router(auth_router)
      return app
  ```

- [ ] **7.12** TDD — write the auth-me-401 test. Create `apps/api/tests/test_auth.py`:
  ```python
  """Auth flow contract tests."""

  import pytest
  from httpx import AsyncClient


  @pytest.mark.asyncio
  async def test_users_me_unauthenticated_returns_401(client: AsyncClient) -> None:
      """GET /users/me with no cookie → 401."""
      response = await client.get("/users/me")
      assert response.status_code == 401


  @pytest.mark.asyncio
  async def test_google_authorize_returns_redirect(client: AsyncClient) -> None:
      """GET /auth/google/authorize → JSON with authorization URL."""
      response = await client.get("/auth/google/authorize")
      # FastAPI-Users returns 200 + {"authorization_url": "..."} (not a 302).
      assert response.status_code == 200
      data = response.json()
      assert "authorization_url" in data
      assert data["authorization_url"].startswith("https://accounts.google.com/")
  ```

- [ ] **7.13** Run pytest. Apply DB migration first if not already applied:
  ```bash
  docker compose -f infra/docker/docker-compose.yml --env-file .env --profile zero up -d postgres
  sleep 5
  cd packages/db && SUITEST_DATABASE_URL=postgresql+asyncpg://suitest:suitest@localhost:5432/suitest \
    uv run alembic upgrade head && cd ../..
  SUITEST_DATABASE_URL=postgresql+asyncpg://suitest:suitest@localhost:5432/suitest \
    SUITEST_OAUTH_GOOGLE_CLIENT_ID=test-client-id \
    SUITEST_OAUTH_GOOGLE_CLIENT_SECRET=test-client-secret \
    uv run pytest apps/api/tests -q
  ```
  expected:
  ```
  4 passed in 0.XXs
  ```

- [ ] **7.14** Create the web login route. Create `apps/web/src/routes/login.tsx`:
  ```tsx
  import { createFileRoute } from "@tanstack/react-router";

  function Login(): React.ReactElement {
    const apiUrl = import.meta.env["VITE_API_URL"] ?? "http://localhost:4000";

    const onGoogle = async (): Promise<void> => {
      const res = await fetch(`${apiUrl}/auth/google/authorize`, { credentials: "include" });
      const data: { authorization_url: string } = await res.json();
      window.location.href = data.authorization_url;
    };

    return (
      <section className="mx-auto flex max-w-sm flex-col gap-6 rounded-lg border border-border bg-elev-1 p-8">
        <h2 className="text-xl font-semibold">Sign in to Suitest</h2>
        <p className="text-sm text-fg-3">
          Use your Google account. We do not store passwords for OAuth users.
        </p>
        <button
          type="button"
          onClick={() => void onGoogle()}
          className="rounded-md bg-accent px-4 py-2 font-medium text-base hover:bg-accent/90"
        >
          Continue with Google
        </button>
      </section>
    );
  }

  export const Route = createFileRoute("/login")({ component: Login });
  ```

- [ ] **7.15** Update `apps/web/src/routeTree.gen.ts` to register the new route:
  ```ts
  /* eslint-disable */
  // Hand-written for M0 — TanStack Router CLI will replace this in M1.
  import { Route as RootRoute } from "./routes/__root";
  import { Route as IndexRoute } from "./routes/index";
  import { Route as LoginRoute } from "./routes/login";

  declare module "@tanstack/react-router" {
    interface FileRoutesByPath {
      "/": { parentRoute: typeof RootRoute };
      "/login": { parentRoute: typeof RootRoute };
    }
  }

  const IndexRouteWithChildren = IndexRoute.update({
    id: "/",
    path: "/",
    getParentRoute: () => RootRoute,
  });

  const LoginRouteWithChildren = LoginRoute.update({
    id: "/login",
    path: "/login",
    getParentRoute: () => RootRoute,
  });

  export const routeTree = RootRoute.addChildren([IndexRouteWithChildren, LoginRouteWithChildren]);
  ```

- [ ] **7.16** Commit:
  ```bash
  git add -A
  git commit -m "feat(api,web): add FastAPI-Users + Google OAuth + login route"
  ```

---

## Task 8: GitHub Actions CI

**Acceptance criterion:** M0-9 (CI green for ruff/mypy/pytest/tsc/eslint/vitest + image build).

- [ ] **8.1** Create `.github/workflows/ci.yml`:
  ```yaml
  name: ci

  on:
    push:
      branches: [main]
    pull_request:
      branches: [main]

  concurrency:
    group: ${{ github.workflow }}-${{ github.ref }}
    cancel-in-progress: true

  jobs:
    python-lint:
      runs-on: ubuntu-24.04
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v3
          with:
            enable-cache: true
        - name: Set up Python
          run: uv python install 3.12
        - name: Sync deps
          run: uv sync --all-packages
        - name: Ruff check
          run: uv run ruff check .
        - name: Ruff format check
          run: uv run ruff format --check .
        - name: Mypy
          run: uv run mypy apps packages

    python-test:
      runs-on: ubuntu-24.04
      services:
        postgres:
          image: pgvector/pgvector:pg16
          env:
            POSTGRES_USER: suitest
            POSTGRES_PASSWORD: suitest
            POSTGRES_DB: suitest
          ports: ["5432:5432"]
          options: >-
            --health-cmd "pg_isready -U suitest"
            --health-interval 5s
            --health-timeout 5s
            --health-retries 10
        redis:
          image: redis:7-alpine
          ports: ["6379:6379"]
          options: >-
            --health-cmd "redis-cli ping"
            --health-interval 5s
            --health-timeout 3s
            --health-retries 10
      env:
        SUITEST_DATABASE_URL: postgresql+asyncpg://suitest:suitest@localhost:5432/suitest
        SUITEST_REDIS_URL: redis://localhost:6379/0
        SUITEST_AUTH_SECRET: ci-secret-32-characters-minimum-for-jwt
        SUITEST_ENCRYPTION_KEY: Y2ktZW5jcnlwdGlvbi1rZXktMzItYnl0ZS1iYXNlNjQ=
        SUITEST_OAUTH_GOOGLE_CLIENT_ID: ci-client-id
        SUITEST_OAUTH_GOOGLE_CLIENT_SECRET: ci-client-secret
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v3
          with:
            enable-cache: true
        - run: uv python install 3.12
        - run: uv sync --all-packages
        - name: Apply migrations
          working-directory: packages/db
          run: uv run alembic upgrade head
        - name: Pytest
          run: uv run pytest -q

    ts-lint:
      runs-on: ubuntu-24.04
      defaults:
        run:
          working-directory: apps/web
      steps:
        - uses: actions/checkout@v4
        - uses: pnpm/action-setup@v4
          with:
            version: 9
        - uses: actions/setup-node@v4
          with:
            node-version: 20
            cache: pnpm
            cache-dependency-path: apps/web/pnpm-lock.yaml
        - run: pnpm install --frozen-lockfile
        - run: pnpm typecheck
        - run: pnpm lint

    ts-test:
      runs-on: ubuntu-24.04
      defaults:
        run:
          working-directory: apps/web
      steps:
        - uses: actions/checkout@v4
        - uses: pnpm/action-setup@v4
          with:
            version: 9
        - uses: actions/setup-node@v4
          with:
            node-version: 20
            cache: pnpm
            cache-dependency-path: apps/web/pnpm-lock.yaml
        - run: pnpm install --frozen-lockfile
        - run: pnpm test

    build-images:
      if: github.event_name == 'pull_request'
      runs-on: ubuntu-24.04
      needs: [python-lint, python-test, ts-lint, ts-test]
      steps:
        - uses: actions/checkout@v4
        - uses: docker/setup-buildx-action@v3
        - name: Build api image (no push)
          uses: docker/build-push-action@v6
          with:
            context: .
            file: infra/docker/Dockerfile.api
            push: false
            tags: suitest-api:ci
            cache-from: type=gha
            cache-to: type=gha,mode=max
        - name: Build runner image (no push)
          uses: docker/build-push-action@v6
          with:
            context: .
            file: infra/docker/Dockerfile.runner
            push: false
            tags: suitest-runner:ci
            cache-from: type=gha
            cache-to: type=gha,mode=max
        - name: Build web image (no push)
          uses: docker/build-push-action@v6
          with:
            context: .
            file: infra/docker/Dockerfile.web
            push: false
            tags: suitest-web:ci
            cache-from: type=gha
            cache-to: type=gha,mode=max
  ```

- [ ] **8.2** Local sanity (optional) using `act`:
  ```bash
  act -j python-lint --container-architecture linux/amd64
  ```
  expected:
  ```
  Job succeeded
  ```

- [ ] **8.3** Push branch + watch CI run (the `build-images` job will fail until Task 9 adds Dockerfiles — that's expected at this commit and resolves itself after Task 9 lands in the same PR / merge):
  ```bash
  git add -A
  git commit -m "ci: add GitHub Actions workflow (lint/typecheck/test/build)"
  ```

---

## Task 9: Single `docker compose up` brings entire stack up

**Acceptance criterion:** M0-10 (single command boots api + runner + web + pg + redis + minio).

- [ ] **9.1** Create `apps/runner/pyproject.toml`:
  ```toml
  [project]
  name = "suitest-runner"
  version = "0.1.0"
  description = "Suitest ARQ worker (placeholder for M0; full runner in M1)"
  requires-python = ">=3.12,<3.13"
  dependencies = [
    "arq>=0.26.3",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "structlog>=24.4.0",
    "suitest-core",
    "suitest-shared",
  ]

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/suitest_runner"]
  ```

- [ ] **9.2** Create `apps/runner/src/suitest_runner/__init__.py`:
  ```python
  """Suitest ARQ worker (M0 placeholder)."""

  __version__ = "0.1.0"
  ```

- [ ] **9.3** Create `apps/runner/src/suitest_runner/worker.py` (placeholder so the container has a process to run):
  ```python
  """ARQ worker entrypoint. M0 has no jobs registered — real jobs ship in M1."""

  from __future__ import annotations

  import os

  from arq.connections import RedisSettings


  async def heartbeat(ctx: dict[str, object]) -> str:
      """Dummy job so ARQ has at least one registered function in M0."""
      _ = ctx
      return "ok"


  class WorkerSettings:
      """ARQ worker settings consumed by `arq` CLI."""

      functions = [heartbeat]
      redis_settings = RedisSettings.from_dsn(
          os.getenv("SUITEST_REDIS_URL", "redis://redis:6379/0")
      )
      max_jobs = 8
      job_timeout = 60
      keep_result = 60
  ```

- [ ] **9.4** Create `apps/runner/src/suitest_runner/__main__.py`:
  ```python
  """`python -m suitest_runner` entrypoint."""

  from arq.cli import cli


  def main() -> None:
      """Delegate to the ARQ CLI."""
      cli.main(["suitest_runner.worker.WorkerSettings"])


  if __name__ == "__main__":
      main()
  ```

- [ ] **9.5** Create `infra/docker/Dockerfile.api`:
  ```dockerfile
  # syntax=docker/dockerfile:1.7

  FROM python:3.12-slim AS base
  ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
  RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates build-essential libpq-dev \
      && rm -rf /var/lib/apt/lists/*
  RUN pip install --no-cache-dir uv==0.5.4

  WORKDIR /app
  COPY pyproject.toml uv.lock* ./
  COPY apps/api/ apps/api/
  COPY apps/runner/ apps/runner/
  COPY packages/ packages/
  RUN uv sync --frozen --no-dev --package suitest-api

  EXPOSE 4000
  HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:4000/health || exit 1

  CMD ["uv", "run", "uvicorn", "suitest_api.main:app", "--host", "0.0.0.0", "--port", "4000"]
  ```

- [ ] **9.6** Create `infra/docker/Dockerfile.runner`:
  ```dockerfile
  # syntax=docker/dockerfile:1.7

  FROM python:3.12-slim AS base
  ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
  RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates build-essential libpq-dev \
      && rm -rf /var/lib/apt/lists/*
  RUN pip install --no-cache-dir uv==0.5.4

  WORKDIR /app
  COPY pyproject.toml uv.lock* ./
  COPY apps/runner/ apps/runner/
  COPY apps/api/ apps/api/
  COPY packages/ packages/
  RUN uv sync --frozen --no-dev --package suitest-runner

  CMD ["uv", "run", "arq", "suitest_runner.worker.WorkerSettings"]
  ```

- [ ] **9.7** Create `infra/docker/Dockerfile.web` (multi-stage):
  ```dockerfile
  # syntax=docker/dockerfile:1.7

  FROM node:20-bookworm-slim AS builder
  WORKDIR /app
  RUN corepack enable && corepack prepare pnpm@9 --activate
  COPY pnpm-workspace.yaml package.json* ./
  COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/
  RUN cd apps/web && pnpm install --frozen-lockfile
  COPY apps/web/ apps/web/
  ARG VITE_API_URL=http://localhost:4000
  ENV VITE_API_URL=$VITE_API_URL
  RUN cd apps/web && pnpm build

  FROM nginx:1.27-alpine AS runtime
  COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
  COPY --from=builder /app/apps/web/dist/ /usr/share/nginx/html/
  EXPOSE 80
  HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost/healthz || exit 1
  ```

- [ ] **9.8** Create `infra/docker/nginx.conf`:
  ```nginx
  server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    location /healthz {
      access_log off;
      return 200 "ok\n";
      add_header Content-Type text/plain;
    }

    location / {
      try_files $uri $uri/ /index.html;
    }
  }
  ```

- [ ] **9.9** Extend `infra/docker/docker-compose.yml` — append `api`, `runner`, `web` services to the existing `services:` block (and add a `migrate` job). Final file looks like:
  ```yaml
  name: suitest

  x-suitest-env: &suitest-env
    SUITEST_DATABASE_URL: ${SUITEST_DATABASE_URL}
    SUITEST_REDIS_URL: ${SUITEST_REDIS_URL}
    SUITEST_S3_ENDPOINT: ${SUITEST_S3_ENDPOINT}
    SUITEST_S3_BUCKET: ${SUITEST_S3_BUCKET}
    SUITEST_S3_ACCESS_KEY: ${SUITEST_S3_ACCESS_KEY}
    SUITEST_S3_SECRET_KEY: ${SUITEST_S3_SECRET_KEY}
    SUITEST_LLM_PROVIDER: ${SUITEST_LLM_PROVIDER:-}
    SUITEST_ENCRYPTION_KEY: ${SUITEST_ENCRYPTION_KEY}
    SUITEST_AUTH_SECRET: ${SUITEST_AUTH_SECRET}
    SUITEST_WEB_URL: ${SUITEST_WEB_URL}
    SUITEST_API_URL: ${SUITEST_API_URL}
    SUITEST_OAUTH_GOOGLE_CLIENT_ID: ${SUITEST_OAUTH_GOOGLE_CLIENT_ID:-}
    SUITEST_OAUTH_GOOGLE_CLIENT_SECRET: ${SUITEST_OAUTH_GOOGLE_CLIENT_SECRET:-}

  services:
    postgres:
      image: pgvector/pgvector:pg16
      profiles: ["zero", "cloud", "local", "dev"]
      restart: unless-stopped
      environment:
        POSTGRES_USER: suitest
        POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-suitest}
        POSTGRES_DB: suitest
      ports: ["5432:5432"]
      volumes: [pgdata:/var/lib/postgresql/data]
      healthcheck:
        test: ["CMD-SHELL", "pg_isready -U suitest -d suitest"]
        interval: 5s
        timeout: 5s
        retries: 10

    redis:
      image: redis:7-alpine
      profiles: ["zero", "cloud", "local", "dev"]
      restart: unless-stopped
      command: ["redis-server", "--appendonly", "yes"]
      ports: ["6379:6379"]
      volumes: [redisdata:/data]
      healthcheck:
        test: ["CMD", "redis-cli", "ping"]
        interval: 5s
        timeout: 3s
        retries: 10

    minio:
      image: minio/minio:latest
      profiles: ["zero", "cloud", "local", "dev"]
      restart: unless-stopped
      command: ["server", "/data", "--console-address", ":9001"]
      environment:
        MINIO_ROOT_USER: ${SUITEST_S3_ACCESS_KEY:-minioadmin}
        MINIO_ROOT_PASSWORD: ${SUITEST_S3_SECRET_KEY:-minioadmin}
      ports:
        - "9000:9000"
        - "9001:9001"
      volumes: [miniodata:/data]
      healthcheck:
        test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/ready"]
        interval: 10s
        timeout: 5s
        retries: 10

    minio-init:
      image: minio/mc:latest
      profiles: ["zero", "cloud", "local", "dev"]
      depends_on:
        minio: { condition: service_healthy }
      entrypoint: >
        /bin/sh -c "
          mc alias set local http://minio:9000 ${SUITEST_S3_ACCESS_KEY:-minioadmin} ${SUITEST_S3_SECRET_KEY:-minioadmin} &&
          mc mb --ignore-existing local/${SUITEST_S3_BUCKET:-suitest-artifacts} &&
          mc anonymous set download local/${SUITEST_S3_BUCKET:-suitest-artifacts} ||
          echo 'bucket init done';
        "
      restart: "no"

    migrate:
      build:
        context: ../..
        dockerfile: infra/docker/Dockerfile.api
      profiles: ["zero", "cloud", "local", "dev"]
      environment: *suitest-env
      depends_on:
        postgres: { condition: service_healthy }
      command: ["uv", "run", "alembic", "-c", "packages/db/alembic.ini", "upgrade", "head"]
      restart: "no"

    api:
      build:
        context: ../..
        dockerfile: infra/docker/Dockerfile.api
      profiles: ["zero", "cloud", "local", "dev"]
      environment: *suitest-env
      depends_on:
        postgres: { condition: service_healthy }
        redis: { condition: service_started }
        minio: { condition: service_healthy }
        migrate: { condition: service_completed_successfully }
      ports: ["4000:4000"]
      healthcheck:
        test: ["CMD", "curl", "-fsS", "http://localhost:4000/health"]
        interval: 15s
        timeout: 5s
        start_period: 20s
        retries: 5

    runner:
      build:
        context: ../..
        dockerfile: infra/docker/Dockerfile.runner
      profiles: ["zero", "cloud", "local", "dev"]
      environment: *suitest-env
      depends_on:
        api: { condition: service_healthy }
        redis: { condition: service_started }

    web:
      build:
        context: ../..
        dockerfile: infra/docker/Dockerfile.web
        args:
          VITE_API_URL: ${SUITEST_API_URL}
      profiles: ["zero", "cloud", "local", "dev"]
      depends_on:
        api: { condition: service_healthy }
      ports: ["3000:80"]
      healthcheck:
        test: ["CMD", "wget", "-qO-", "http://localhost/healthz"]
        interval: 30s
        timeout: 5s
        retries: 3

  volumes:
    pgdata:
    redisdata:
    miniodata:

  networks:
    default:
      name: suitest
  ```

- [ ] **9.10** Verify single-command boot:
  ```bash
  docker compose -f infra/docker/docker-compose.yml --env-file .env --profile zero build
  docker compose -f infra/docker/docker-compose.yml --env-file .env --profile zero up -d
  sleep 25
  docker compose -f infra/docker/docker-compose.yml ps
  curl -s http://localhost:4000/health
  curl -s http://localhost:4000/capabilities
  curl -sI http://localhost:3000/
  ```
  expected:
  - `docker compose ps` shows postgres/redis/minio/api/web `(healthy)`, `minio-init` and `migrate` `Exited (0)`, runner `Up`.
  - `curl /health` → `{"status":"ok","service":"api","version":"0.1.0"}`
  - `curl /capabilities` JSON contains `"tier":"ZERO"`.
  - `curl -I /` returns HTTP/200 from nginx.

- [ ] **9.11** Tear down:
  ```bash
  docker compose -f infra/docker/docker-compose.yml down
  ```

- [ ] **9.12** Commit:
  ```bash
  git add -A
  git commit -m "feat(infra): single docker compose up boots api+runner+web+pg+redis+minio"
  ```

---

## Task 10: Helm chart skeleton + `helm lint`

**Acceptance criterion:** M0-11 (Helm chart skeleton lulus `helm lint`).

- [ ] **10.1** Create `infra/helm/suitest/Chart.yaml`:
  ```yaml
  apiVersion: v2
  name: suitest
  description: MCP-native testing platform — OSS self-host chart
  type: application
  version: 0.1.0
  appVersion: "0.1.0"
  kubeVersion: ">=1.27.0-0"
  home: https://suitest.dev
  sources:
    - https://github.com/suitest-dev/suitest
  maintainers:
    - name: Suitest Maintainers
      email: maintainers@suitest.dev
  keywords:
    - testing
    - tcm
    - mcp
    - playwright
    - self-hosted
  ```

- [ ] **10.2** Create `infra/helm/suitest/values.yaml`:
  ```yaml
  suitest:
    tier: zero
    autonomyDefault: manual

  image:
    registry: ghcr.io/suitest-dev
    apiRepository: suitest-api
    runnerRepository: suitest-runner
    webRepository: suitest-web
    tag: "0.1.0"
    pullPolicy: IfNotPresent
    pullSecrets: []

  llm:
    enabled: false
    provider: none
    model: ""
    baseUrl: ""
    apiKeySecretRef:
      name: ""
      key: api-key

  embeddings:
    backend: none
    model: ""
    dim: 384

  api:
    replicaCount: 2
    service:
      type: ClusterIP
      port: 4000
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 1000m
        memory: 1Gi

  web:
    replicaCount: 2
    service:
      type: ClusterIP
      port: 80
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi

  ingress:
    enabled: false
    className: nginx
    annotations: {}
    hosts:
      - host: suitest.local
        paths:
          - path: /
            pathType: Prefix
    tls: []

  postgres:
    external: true
    host: postgres
    port: 5432
    database: suitest
    userSecretRef:
      name: suitest-pg
      key: user
    passwordSecretRef:
      name: suitest-pg
      key: password

  redis:
    external: true
    url: redis://redis:6379/0

  s3:
    external: true
    endpoint: http://minio:9000
    bucket: suitest-artifacts

  serviceAccount:
    create: true
    name: ""
    annotations: {}

  podSecurityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000

  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: ["ALL"]
  ```

- [ ] **10.3** Create `infra/helm/suitest/templates/_helpers.tpl`:
  ```yaml
  {{/*
  Common labels + naming helpers.
  */}}

  {{- define "suitest.name" -}}
  {{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
  {{- end -}}

  {{- define "suitest.fullname" -}}
  {{- $name := default .Chart.Name .Values.nameOverride -}}
  {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
  {{- end -}}

  {{- define "suitest.chart" -}}
  {{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
  {{- end -}}

  {{- define "suitest.labels" -}}
  helm.sh/chart: {{ include "suitest.chart" . }}
  app.kubernetes.io/name: {{ include "suitest.name" . }}
  app.kubernetes.io/instance: {{ .Release.Name }}
  app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
  app.kubernetes.io/managed-by: {{ .Release.Service }}
  suitest.dev/tier: {{ .Values.suitest.tier | quote }}
  {{- end -}}

  {{- define "suitest.selectorLabels" -}}
  app.kubernetes.io/name: {{ include "suitest.name" . }}
  app.kubernetes.io/instance: {{ .Release.Name }}
  {{- end -}}

  {{- define "suitest.serviceAccountName" -}}
  {{- if .Values.serviceAccount.create -}}
  {{- default (include "suitest.fullname" .) .Values.serviceAccount.name -}}
  {{- else -}}
  {{- default "default" .Values.serviceAccount.name -}}
  {{- end -}}
  {{- end -}}
  ```

- [ ] **10.4** Create `infra/helm/suitest/templates/configmap.yaml`:
  ```yaml
  apiVersion: v1
  kind: ConfigMap
  metadata:
    name: {{ include "suitest.fullname" . }}-config
    labels:
      {{- include "suitest.labels" . | nindent 4 }}
  data:
    SUITEST_LLM_PROVIDER: {{ .Values.llm.provider | quote }}
    SUITEST_LLM_MODEL: {{ .Values.llm.model | quote }}
    SUITEST_LLM_BASE_URL: {{ .Values.llm.baseUrl | quote }}
    SUITEST_EMBEDDINGS_BACKEND: {{ .Values.embeddings.backend | quote }}
    SUITEST_S3_ENDPOINT: {{ .Values.s3.endpoint | quote }}
    SUITEST_S3_BUCKET: {{ .Values.s3.bucket | quote }}
    SUITEST_REDIS_URL: {{ .Values.redis.url | quote }}
  ```

- [ ] **10.5** Create `infra/helm/suitest/templates/secret.yaml`:
  ```yaml
  {{- if not (lookup "v1" "Secret" .Release.Namespace (printf "%s-secret" (include "suitest.fullname" .))) }}
  apiVersion: v1
  kind: Secret
  metadata:
    name: {{ include "suitest.fullname" . }}-secret
    labels:
      {{- include "suitest.labels" . | nindent 4 }}
  type: Opaque
  stringData:
    SUITEST_AUTH_SECRET: {{ randAlphaNum 32 | quote }}
    SUITEST_ENCRYPTION_KEY: {{ randAlphaNum 32 | b64enc | quote }}
  {{- end }}
  ```

- [ ] **10.6** Create `infra/helm/suitest/templates/api-deployment.yaml`:
  ```yaml
  apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: {{ include "suitest.fullname" . }}-api
    labels:
      {{- include "suitest.labels" . | nindent 4 }}
      app.kubernetes.io/component: api
  spec:
    replicas: {{ .Values.api.replicaCount }}
    selector:
      matchLabels:
        {{- include "suitest.selectorLabels" . | nindent 6 }}
        app.kubernetes.io/component: api
    template:
      metadata:
        labels:
          {{- include "suitest.selectorLabels" . | nindent 8 }}
          app.kubernetes.io/component: api
      spec:
        serviceAccountName: {{ include "suitest.serviceAccountName" . }}
        securityContext:
          {{- toYaml .Values.podSecurityContext | nindent 8 }}
        containers:
          - name: api
            image: "{{ .Values.image.registry }}/{{ .Values.image.apiRepository }}:{{ .Values.image.tag }}"
            imagePullPolicy: {{ .Values.image.pullPolicy }}
            securityContext:
              {{- toYaml .Values.securityContext | nindent 14 }}
            ports:
              - containerPort: 4000
                name: http
            envFrom:
              - configMapRef:
                  name: {{ include "suitest.fullname" . }}-config
              - secretRef:
                  name: {{ include "suitest.fullname" . }}-secret
            livenessProbe:
              httpGet: { path: /health, port: http }
              periodSeconds: 30
            readinessProbe:
              httpGet: { path: /health, port: http }
              periodSeconds: 10
            resources:
              {{- toYaml .Values.api.resources | nindent 14 }}
        {{- with .Values.image.pullSecrets }}
        imagePullSecrets:
          {{- toYaml . | nindent 10 }}
        {{- end }}
  ```

- [ ] **10.7** Create `infra/helm/suitest/templates/api-service.yaml`:
  ```yaml
  apiVersion: v1
  kind: Service
  metadata:
    name: {{ include "suitest.fullname" . }}-api
    labels:
      {{- include "suitest.labels" . | nindent 4 }}
      app.kubernetes.io/component: api
  spec:
    type: {{ .Values.api.service.type }}
    ports:
      - port: {{ .Values.api.service.port }}
        targetPort: http
        protocol: TCP
        name: http
    selector:
      {{- include "suitest.selectorLabels" . | nindent 4 }}
      app.kubernetes.io/component: api
  ```

- [ ] **10.8** Create `infra/helm/suitest/templates/web-deployment.yaml`:
  ```yaml
  apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: {{ include "suitest.fullname" . }}-web
    labels:
      {{- include "suitest.labels" . | nindent 4 }}
      app.kubernetes.io/component: web
  spec:
    replicas: {{ .Values.web.replicaCount }}
    selector:
      matchLabels:
        {{- include "suitest.selectorLabels" . | nindent 6 }}
        app.kubernetes.io/component: web
    template:
      metadata:
        labels:
          {{- include "suitest.selectorLabels" . | nindent 8 }}
          app.kubernetes.io/component: web
      spec:
        serviceAccountName: {{ include "suitest.serviceAccountName" . }}
        securityContext:
          {{- toYaml .Values.podSecurityContext | nindent 8 }}
        containers:
          - name: web
            image: "{{ .Values.image.registry }}/{{ .Values.image.webRepository }}:{{ .Values.image.tag }}"
            imagePullPolicy: {{ .Values.image.pullPolicy }}
            ports:
              - containerPort: 80
                name: http
            livenessProbe:
              httpGet: { path: /healthz, port: http }
              periodSeconds: 30
            readinessProbe:
              httpGet: { path: /healthz, port: http }
              periodSeconds: 10
            resources:
              {{- toYaml .Values.web.resources | nindent 14 }}
        {{- with .Values.image.pullSecrets }}
        imagePullSecrets:
          {{- toYaml . | nindent 10 }}
        {{- end }}
  ```

- [ ] **10.9** Create `infra/helm/suitest/templates/web-service.yaml`:
  ```yaml
  apiVersion: v1
  kind: Service
  metadata:
    name: {{ include "suitest.fullname" . }}-web
    labels:
      {{- include "suitest.labels" . | nindent 4 }}
      app.kubernetes.io/component: web
  spec:
    type: {{ .Values.web.service.type }}
    ports:
      - port: {{ .Values.web.service.port }}
        targetPort: http
        protocol: TCP
        name: http
    selector:
      {{- include "suitest.selectorLabels" . | nindent 4 }}
      app.kubernetes.io/component: web
  ```

- [ ] **10.10** Create `infra/helm/suitest/templates/serviceaccount.yaml`:
  ```yaml
  {{- if .Values.serviceAccount.create }}
  apiVersion: v1
  kind: ServiceAccount
  metadata:
    name: {{ include "suitest.serviceAccountName" . }}
    labels:
      {{- include "suitest.labels" . | nindent 4 }}
    {{- with .Values.serviceAccount.annotations }}
    annotations:
      {{- toYaml . | nindent 4 }}
    {{- end }}
  {{- end }}
  ```

- [ ] **10.11** Create `infra/helm/suitest/.helmignore`:
  ```
  # Patterns to ignore when building packages.
  .DS_Store
  .git/
  .gitignore
  .vscode/
  .idea/
  *.tmproj
  *.bak
  *.swp
  *~
  .project
  .settings/
  ```

- [ ] **10.12** Run `helm lint`:
  ```bash
  helm lint infra/helm/suitest/
  ```
  expected:
  ```
  ==> Linting infra/helm/suitest/
  [INFO] Chart.yaml: icon is recommended

  1 chart(s) linted, 0 chart(s) failed
  ```

- [ ] **10.13** Template render sanity check:
  ```bash
  helm template suitest infra/helm/suitest/ --set ingress.enabled=true > /tmp/suitest-rendered.yaml
  head -40 /tmp/suitest-rendered.yaml
  ```
  expected: emits `kind: ConfigMap`, `kind: Secret`, `kind: Deployment` blocks without templating errors.

- [ ] **10.14** Commit:
  ```bash
  git add -A
  git commit -m "feat(infra): add helm chart skeleton (api+web deployments, service, configmap)"
  ```

---

## Task 11: Definition of Done — manual smoke + tag

**Acceptance criterion:** M0 DoD (clone → compose up → login → see ZERO badge on `/dashboard`).

- [ ] **11.1** Add a minimal `/dashboard` route so the OAuth redirect target exists. Create `apps/web/src/routes/dashboard.tsx`:
  ```tsx
  import { createFileRoute } from "@tanstack/react-router";

  import { useCapabilities } from "@/stores/use-capabilities";

  function Dashboard(): React.ReactElement {
    const data = useCapabilities((s) => s.data);
    return (
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">Dashboard</h2>
        <p className="text-fg-3">
          Empty dashboard (M0 skeleton). Full KPIs ship in M1.
        </p>
        {data ? (
          <pre className="rounded-md border border-border bg-elev-1 p-4 font-mono text-xs text-fg-3">
            tier={data.tier} provider={data.llm_provider ?? "none"}
          </pre>
        ) : null}
      </section>
    );
  }

  export const Route = createFileRoute("/dashboard")({ component: Dashboard });
  ```

- [ ] **11.2** Update `apps/web/src/routeTree.gen.ts` to register `/dashboard`:
  ```ts
  /* eslint-disable */
  // Hand-written for M0 — TanStack Router CLI will replace this in M1.
  import { Route as RootRoute } from "./routes/__root";
  import { Route as IndexRoute } from "./routes/index";
  import { Route as LoginRoute } from "./routes/login";
  import { Route as DashboardRoute } from "./routes/dashboard";

  declare module "@tanstack/react-router" {
    interface FileRoutesByPath {
      "/": { parentRoute: typeof RootRoute };
      "/login": { parentRoute: typeof RootRoute };
      "/dashboard": { parentRoute: typeof RootRoute };
    }
  }

  const IndexRouteWithChildren = IndexRoute.update({
    id: "/",
    path: "/",
    getParentRoute: () => RootRoute,
  });

  const LoginRouteWithChildren = LoginRoute.update({
    id: "/login",
    path: "/login",
    getParentRoute: () => RootRoute,
  });

  const DashboardRouteWithChildren = DashboardRoute.update({
    id: "/dashboard",
    path: "/dashboard",
    getParentRoute: () => RootRoute,
  });

  export const routeTree = RootRoute.addChildren([
    IndexRouteWithChildren,
    LoginRouteWithChildren,
    DashboardRouteWithChildren,
  ]);
  ```

- [ ] **11.3** Execute the manual DoD smoke procedure (document inline; the implementer runs these literally):
  1. Provision a fresh working tree:
     ```bash
     cd /tmp
     rm -rf suitest-smoke
     git clone <repo-url> suitest-smoke
     cd suitest-smoke
     ```
  2. Generate secrets and write `.env`:
     ```bash
     cp .env.example .env
     python -c "import secrets; print('SUITEST_AUTH_SECRET=' + secrets.token_hex(32))" >> .env
     python -c "import secrets,base64; print('SUITEST_ENCRYPTION_KEY=' + base64.b64encode(secrets.token_bytes(32)).decode())" >> .env
     ```
     (Then dedupe — keep only the generated values for those two keys.)
  3. Set OAuth values in `.env`:
     ```env
     SUITEST_OAUTH_GOOGLE_CLIENT_ID=<your-client-id>
     SUITEST_OAUTH_GOOGLE_CLIENT_SECRET=<your-client-secret>
     ```
     (Register `http://localhost:4000/auth/google/callback` as an authorized redirect URI in Google Cloud Console.)
  4. Boot:
     ```bash
     docker compose -f infra/docker/docker-compose.yml --env-file .env --profile zero up -d --build
     sleep 30
     docker compose -f infra/docker/docker-compose.yml ps
     ```
     expected: all services healthy except `minio-init` + `migrate` which show `Exited (0)`.
  5. Verify API:
     ```bash
     curl -s http://localhost:4000/health
     curl -s http://localhost:4000/capabilities | python -m json.tool
     ```
     expected: `/capabilities` returns JSON with `"tier": "ZERO"` and `autonomy.default == "manual"`.
  6. Visit web in browser:
     - Open `http://localhost:3000/` — see "Welcome to Suitest" + `ZERO` tier badge top-right.
     - Open `http://localhost:3000/login` — see "Continue with Google" button.
     - Click button → redirect to Google consent screen → approve → redirected back to `http://localhost:3000/dashboard` with `ZERO` badge still visible and "Dashboard" heading.
  7. Tear down:
     ```bash
     docker compose -f infra/docker/docker-compose.yml down -v
     ```

- [ ] **11.4** Update `README.md` to point at the smoke procedure (no other doc edits required — DEPLOYMENT.md is already authoritative). Append below the existing Quickstart in `README.md`:
  ```markdown
  ## Manual DoD smoke

  See M0 plan task 11 (`docs/superpowers/plans/2026-05-26-plan-01-m0-skeleton.md`) for the
  end-to-end clone → compose → login → dashboard smoke procedure.
  ```

- [ ] **11.5** Final commit:
  ```bash
  git add -A
  git commit -m "feat(web): add /dashboard route + document M0 DoD smoke procedure"
  ```

- [ ] **11.6** Tag the milestone:
  ```bash
  git tag -a v0.1.0-m0 -m "M0 — Skeleton OSS complete: bootable monorepo, ZERO tier, OAuth login"
  ```
  expected (after `git show v0.1.0-m0 --no-patch`):
  ```
  tag v0.1.0-m0
  Tagger: ...
  Date:   ...

      M0 — Skeleton OSS complete: bootable monorepo, ZERO tier, OAuth login
  ```

- [ ] **11.7** Verify acceptance coverage map (sanity check before declaring M0 done):
  - M0-1 ← Task 0 (uv + pnpm workspaces)
  - M0-2 ← Task 1 (ruff/mypy/eslint/prettier + pre-commit)
  - M0-3 ← Task 4 (Vite + React 19 + Tailwind 4 + Geist)
  - M0-4 ← Tasks 2 + 3 (FastAPI /health + /capabilities)
  - M0-5 ← Task 5 (compose: pg+pgvector, redis, minio)
  - M0-6 ← Task 6 (SQLAlchemy async + Alembic init migration)
  - M0-7 ← deferred to M1 (full seed script lands with the data model)
  - M0-8 ← Task 7 (FastAPI-Users + Google OAuth → `/dashboard`)
  - M0-9 ← Task 8 (GitHub Actions CI)
  - M0-10 ← Task 9 (single `docker compose up`)
  - M0-11 ← Task 10 (Helm skeleton + `helm lint` green)

  **Note on M0-7:** ROADMAP §M0 lists a "Nusantara Retail" seed script. The data model has not been authored yet (DATA_MODEL.md lands with M1), and a one-row workspace insert is insufficient to satisfy that criterion. Track as a gap: implement in the M1a plan together with the full schema. Surfaced in the spec-gaps note below.

---

## Self-review checklist (completed inline)

1. **Every M0 acceptance criterion covered.** ✓ — see §11.7. M0-7 surfaced as deferred to M1 with rationale.
2. **No `TBD` / `TODO` / placeholder strings in code blocks.** ✓ — every block is end-to-end paste-able.
3. **Types and function names consistent across tasks.** ✓ — `CapabilitySnapshot` flows core → router; `Workspace.id` uses `cuid2.new_id`; auth uses `User`, `OAuthAccount`.
4. **Code present in every step that touches code.** ✓ — config files, modules, tests, Dockerfiles, Helm templates, nginx conf all inline.
5. **Exact paths everywhere.** ✓ — all `apps/...`, `packages/...`, `infra/...`, `.github/...` paths spelled out.

## Spec gaps surfaced

- **M0-7 (Nusantara Retail seed):** ROADMAP M0 lists a full seed script. The seed requires the M1 data model (projects, users-in-workspace, roles, suites). This plan covers a minimal `Workspace` model only — sufficient to validate the engine/migration pipeline but not the seed. Recommend folding M0-7 into the first M1a plan together with the full DATA_MODEL.md schema.
- **`@tailwindcss/vite` is currently a beta release.** Pinned `^4.0.0-beta.4` — bump to GA when Tailwind 4 final ships.
- **`TanStack Router` route tree:** M0 uses a hand-written `routeTree.gen.ts`. M1 should adopt the `@tanstack/router-plugin/vite` plugin to autogenerate it.
- **Pre-commit `mypy` hook duplicates the CI mypy step.** Intentional for fast local feedback; revisit if hook cold-start becomes a friction point.
