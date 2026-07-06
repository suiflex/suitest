---
title: Install from source
description: Set up a Suitest development environment with uv and pnpm, run the dev servers, and try the seeded demo.
---

Run Suitest from a repository checkout when you want to develop against it or
contribute. The app processes (API, web, runner) run natively on your machine;
only the datastores run in Docker.

## Requirements

- Python 3.12 with [uv](https://docs.astral.sh/uv/)
- Node.js 20 with [pnpm](https://pnpm.io/)
- Docker (for Postgres, Redis, and MinIO)

Python dependencies are managed as a uv workspace, frontend dependencies as a
pnpm workspace.

## Set up

Clone and start the backing services:

```bash
git clone https://github.com/suiflex/suitest && cd suitest
docker compose -f infra/docker/docker-compose.yml up -d postgres redis minio
```

Then run the one-shot setup:

```bash
make setup
```

`make setup` chains four targets:

1. `make env`: copies `.env.example` to `.env` if missing
2. `make install`: `uv sync --all-extras --dev`, `pnpm install` in `apps/web`,
   and installs the pre-commit hooks
3. `make migrate`: applies Alembic migrations (`alembic upgrade head`)
4. `make seed`: seeds the database with development data

The seed creates three accounts, all with password `admin123`:

| Account | Role |
|---------|------|
| `maya@nusantararetail.local` | OWNER |
| `ari@nusantararetail.local` | ADMIN |
| `dimas@nusantararetail.local` | QA |

## Start the dev servers

```bash
make dev
```

This starts all three processes together; Ctrl-C stops them all:

- API on <http://localhost:4000> (FastAPI with hot reload; interactive docs at
  `/docs`)
- Web on <http://localhost:3000> (Vite dev server)
- Runner (ARQ worker pulling jobs from Redis)

Start them individually when you only need one:

```bash
make dev-api      # FastAPI on :4000, hot reload
make dev-web      # Vite on :3000
make dev-runner   # ARQ worker
```

## Try the demo

The fastest way to see a full generate-and-run loop is the bundled demo. It
uses Docker for everything, so it works even before `make setup`:

```bash
make demo
```

This builds and boots the full stack plus **Brewly**, a small coffee-shop demo
app, and seeds a runnable suite generated from Brewly's PRD:

- Web UI: <http://localhost:3000>, log in with `demo@suitest.dev` / `demo1234`
- Brewly app: <http://localhost:8089>

Open **Test Cases**, select the Brewly suite, and run it. The suite executes
API and browser steps against the live app and passes at ZERO tier, so no LLM
key is involved.

## Useful make targets

Run `make help` for the full list. The ones you will use most:

| Target | Does |
|--------|------|
| `make dev` | API + web + runner together |
| `make migrate` | Apply pending Alembic migrations |
| `make migrate-new m="add x"` | Create a new migration |
| `make seed` | Seed development data |
| `make lint` / `make lint-fix` | Ruff check / auto-fix |
| `make typecheck` | mypy strict, per package |
| `make test` | Python tests (pytest) |
| `make test-web` | Frontend tests (Vitest) |
| `make check-all` | All linters and typecheckers, no tests |
| `make ci` | Everything CI runs: lint + typecheck + tests |
| `make e2e-real` | Real-backend end-to-end suite (boots api + web + runner) |
| `make docker-up-local` | Compose stack with the Ollama profile |

## Quality gates

Before pushing, `make ci` must pass. It is the same set CI runs:

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy .                     # strict, no Any
uv run pytest                     # pytest-asyncio strict mode
pnpm -C apps/web typecheck && pnpm -C apps/web test
```

## Contributing

If you plan to send a pull request:

- Branch naming: `feat/<scope>-<short-desc>`
- Commits: [Conventional Commits](https://www.conventionalcommits.org/), for
  example `feat(api): add X`
- `docs/ROADMAP.md` in the repository is the single entry point for picking up
  work; one PR covers one acceptance criterion
- A one-time Contributor License Agreement is signed by replying to the CLA
  bot on your first PR; the project is licensed under Apache-2.0

See `CONTRIBUTING.md` and `CLAUDE.md` in the repository for the full rules.

## Next steps

- [Getting started](/docs/guides/getting-started/): the 10-minute user path
- [Docker Compose install](/docs/install/docker/): run it without a checkout
- [Troubleshooting](/docs/help/troubleshooting/): common setup issues
