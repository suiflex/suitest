---
title: Install with Docker Compose
description: Self-host the full Suitest platform with Docker Compose, including database, storage, API, web UI, and runner.
---

Docker Compose is the recommended way to self-host the full Suitest platform on
a single machine: the web TCM, the API, the deterministic runner, and all
backing services.

## What you get

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | Primary database |
| `redis` | `redis:7-alpine` | 6379 | Run queue (ARQ) |
| `minio` | `minio/minio` | 9000, 9001 | Artifact storage (screenshots, video) |
| `api` | `ghcr.io/suiflex/suitest-api` | 4000 | FastAPI backend |
| `web` | `ghcr.io/suiflex/suitest-web` | 3000 | Web UI (nginx) |
| `runner` | `ghcr.io/suiflex/suitest-runner` | none | ARQ worker, dispatches steps through MCP |

The app images are prebuilt and published to GHCR on every `images-v*`
release, so a normal install **pulls** them — no local build. Building from
source (`infra/docker/Dockerfile.*`) remains available for development.

A one-shot `migrate` service runs `alembic upgrade head` before the API starts,
and a `minio-init` service creates the artifact bucket. You do not run
migrations by hand.

## Requirements

- Docker with the Compose plugin
- Around 4 GB of free RAM for the full stack

## Install

Clone the repository and create your env file:

```bash
git clone https://github.com/suiflex/suitest && cd suitest
cp .env.example .env
```

Edit `.env` and set the required secrets plus a super-admin account so you can
log in:

```bash
POSTGRES_PASSWORD=<strong-password>
SUITEST_AUTH_SECRET=<random-hex>          # openssl rand -hex 32
SUITEST_ENCRYPTION_KEY=<random-base64>    # openssl rand -base64 32
SUITEST_SUPERADMIN_EMAIL=admin@example.com
SUITEST_SUPERADMIN_PASSWORD=<strong-password>
```

Then pull the prebuilt images and boot the stack (the compose file lives under
`infra/docker/`, and every service is behind a profile, so pass both flags):

```bash
docker compose -f infra/docker/docker-compose.yml --profile zero pull
docker compose -f infra/docker/docker-compose.yml --profile zero up -d
```

While the repository is private, `docker pull` from GHCR needs a login first:
`docker login ghcr.io -u <github-user>` with a token that has `read:packages`.

Pin a specific image release with `SUITEST_IMAGE_TAG` (defaults to `latest`),
e.g. `SUITEST_IMAGE_TAG=0.1.0`. To build from source instead of pulling, use
`make docker-up-prod` (adds `--build`).

Or use the shortcut (pull + up):

```bash
make docker-up
```

Open <http://localhost:3000> when the containers are healthy.

:::caution
If you leave the super-admin variables unset, the compose file falls back to
the development defaults `maya@nusantararetail.local` / `admin123`. Never ship
those to anything reachable from a network: set your own values in `.env`.
:::

## First login and onboarding

Log in with the super-admin email and password from `.env`. The account is
created idempotently on API startup, but only if no users exist yet, so it
cannot clobber an existing install.

Onboarding is invite-only by default: from **Settings**, generate invite links
for the rest of your team. There is no open sign-up page.

The default tier is **ZERO**: no LLM is configured and no LLM call is ever
made. Everything in the manual TCM and the deterministic runner works at this
tier.

## Key .env values

| Variable | Default | Change it when |
|----------|---------|----------------|
| `POSTGRES_PASSWORD` | `suitest` | Always, before first boot |
| `SUITEST_AUTH_SECRET` | placeholder | Always: `openssl rand -hex 32` |
| `SUITEST_ENCRYPTION_KEY` | placeholder | Always: `openssl rand -base64 32`. Encrypts workspace LLM keys at rest; losing it makes stored LLM configs unreadable |
| `SUITEST_SUPERADMIN_EMAIL` / `SUITEST_SUPERADMIN_PASSWORD` | empty | Always, so you can log in |
| `SUITEST_SUPERADMIN_WORKSPACE_NAME` | `Default Workspace` | Optional: name of the first workspace |
| `SUITEST_WEB_URL` / `SUITEST_API_URL` | `http://localhost:3000` / `http://localhost:4000` | Hosting under a real domain |
| `SUITEST_S3_ACCESS_KEY` / `SUITEST_S3_SECRET_KEY` | `minioadmin` / `minioadmin` | Any non-local deployment |
| `SUITEST_S3_BUCKET` | `suitest-artifacts` | Pointing at an existing bucket |
| `SUITEST_COOKIE_SECURE` | `false` | Set `true` behind HTTPS in production |
| `SUITEST_RUNNER_CONCURRENCY` | `4` | Parallel jobs per runner process |
| `SUITEST_RUNNER_JOB_TIMEOUT_SECONDS` | `1800` | Long E2E suites need more |

:::note
The LLM is not configured through env vars. Providers are set per workspace
from the web UI (**Settings, then LLM**) and the key is AES-GCM encrypted at
rest. See [Capability tiers](/docs/reference/tiers/).
:::

## Profiles

Every service carries a compose profile, so `up` without `--profile` starts
nothing. Available profiles:

| Profile | Adds | Use for |
|---------|------|---------|
| `zero` | the core six services | Default install, no LLM |
| `cloud` | same containers as `zero` | Workspaces using a cloud LLM key |
| `local` | `ollama` + a one-shot model pull | Air-gapped LOCAL-tier inference |
| `demo` | Brewly demo app (port 8089) + demo seeder | The 30-second demo |

Makefile shortcuts: `make docker-up` (zero), `make docker-up-local`,
`make docker-up-cloud`.

The `local` profile pulls a small instruct model (`qwen2.5:0.5b` by default,
override with `SUITEST_LOCAL_SMOKE_MODEL`) into a named volume, so the download
survives restarts.

## Try the demo

```bash
make demo
```

This boots the full stack plus **Brewly**, a small coffee-shop fixture app, and
seeds a runnable test suite generated from its PRD:

- Web UI: <http://localhost:3000>, log in with `demo@suitest.dev` / `demo1234`
- Brewly: <http://localhost:8089>

Open **Test Cases**, pick the "Brewly" suite, and hit **Run** to watch API and
browser steps execute against the live app with screenshots. No LLM key needed.

## Seed data

For non-demo development data (projects, suites, cases):

```bash
make seed
# or, inside the api container:
docker compose -f infra/docker/docker-compose.yml exec api python -m suitest_db.seed
```

Seeding creates three accounts (`maya@`, `ari@`, `dimas@nusantararetail.local`)
sharing the password `admin123`. They are meant for local development only.

## Everyday operations

```bash
make docker-logs        # tail all services
make docker-logs-api    # tail the API only
make docker-ps          # container status
make docker-down        # stop everything, keep data
make docker-clean       # stop and DELETE volumes (destroys data)
```

To pick up code changes, rebuild:

```bash
docker compose -f infra/docker/docker-compose.yml --profile zero up -d --build
```

## Connect your IDE

With the platform running, wire the MCP server to it so IDE-generated cases,
runs, and evidence publish into the web TCM:

```bash
npx -y @suiflex/suitest-mcp init --mode server \
  --api-url http://localhost:4000 --api-key sk_suitest_xxx
```

See [Install the MCP server](/docs/install/mcp-server/) for details and API key
creation.

## Next steps

- [Getting started](/docs/guides/getting-started/): the 10-minute path
- [Self-hosting guide](/docs/guides/self-hosting/): TLS, backups, hardening
- [Kubernetes install](/docs/install/kubernetes/): the Helm chart
- [Environment reference](/docs/reference/environment/): every variable
