---
title: Self-hosting in production
description: Run the Suitest stack with Docker Compose. Required services, environment variables, artifact storage, backups, and upgrades.
---

Suitest self-hosts as a small set of containers behind one compose file:
`infra/docker/docker-compose.yml`. This guide covers running it for real, on a
VPS or internal host, as opposed to the one-command local boot in
[Getting started](/docs/guides/getting-started/). For Kubernetes, see the
[Helm install](/docs/install/kubernetes/).

:::caution
Suitest is pre-v1.0 (Apache-2.0). Expect breaking changes between minor
versions: read the changelog before every upgrade and keep backups current.
:::

## Required services

| Service | Image | Role |
|---------|-------|------|
| `postgres` | `pgvector/pgvector:pg16` | primary database (Postgres 16 with the pgvector extension) |
| `redis` | `redis:7-alpine` | run queue and cache, append-only persistence enabled |
| `minio` + `minio-init` | `minio/minio` | S3-compatible artifact storage; the init job creates the bucket |
| `migrate` | built from source | one-shot `alembic upgrade head`, runs before the API starts |
| `api` | built from source | REST API on port 4000, health at `/health` |
| `runner` | built from source | executes test runs from the queue |
| `web` | built from source | the web UI, served on port 3000 |

An external Postgres, Redis, or S3 endpoint works too: point the
`SUITEST_DATABASE_URL`, `SUITEST_REDIS_URL`, and `SUITEST_S3_*` variables at
your managed services. External Postgres must have the pgvector extension
available (`CREATE EXTENSION IF NOT EXISTS vector;`).

## Boot the stack

```bash
git clone https://github.com/suiflex/suitest
cd suitest
cp .env.example .env
# edit .env before starting (see below)
docker compose -f infra/docker/docker-compose.yml --profile zero up -d
```

Generate real secrets first:

```bash
openssl rand -hex 32     # SUITEST_AUTH_SECRET
openssl rand -base64 32  # SUITEST_ENCRYPTION_KEY
```

Profiles select what runs. `zero` is the default full stack.
`--profile local` additionally starts an in-cluster Ollama (plus a one-shot
model pull) for the LOCAL LLM tier. LLM providers themselves are configured
per workspace in the web UI, not via env: see
[Bring your own LLM](/docs/guides/llm-setup/).

## Environment configuration

All variables use the `SUITEST_` prefix (plus `POSTGRES_PASSWORD` for the
bundled database). The full list lives in the
[environment reference](/docs/reference/environment/); these are the ones a
production install must get right.

### Required secrets

| Variable | Purpose |
|----------|---------|
| `POSTGRES_PASSWORD` | password for the bundled Postgres |
| `SUITEST_AUTH_SECRET` | session and token signing secret (32-char random) |
| `SUITEST_ENCRYPTION_KEY` | base64 32-byte key that AES-encrypts stored LLM provider keys |

### Infrastructure

| Variable | Default (compose) | Purpose |
|----------|-------------------|---------|
| `SUITEST_DATABASE_URL` | in-compose Postgres | `postgresql+asyncpg://...` connection string |
| `SUITEST_REDIS_URL` | `redis://redis:6379/0` | queue and cache |
| `SUITEST_S3_ENDPOINT` | `http://minio:9000` | S3-compatible endpoint |
| `SUITEST_S3_BUCKET` | `suitest-artifacts` | artifact bucket |
| `SUITEST_S3_ACCESS_KEY` / `SUITEST_S3_SECRET_KEY` | `minioadmin` | change these in production |
| `SUITEST_WEB_URL` / `SUITEST_API_URL` | `http://localhost:3000` / `http://localhost:4000` | public URLs, used in links and CORS |
| `SUITEST_COOKIE_SECURE` | `false` | set `true` behind HTTPS so the session cookie is TLS-only |

### Runner and MCP pool tuning

| Variable | Default | Purpose |
|----------|---------|---------|
| `SUITEST_RUNNER_CONCURRENCY` | `4` | parallel jobs per runner worker process |
| `SUITEST_RUNNER_MAX_RETRIES` | `2` | retry budget per job on transient failure |
| `SUITEST_RUNNER_JOB_TIMEOUT_SECONDS` | `1800` | hard wall-clock budget per run job |
| `SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE` | `16` | per-workspace cap on concurrent MCP sessions |
| `SUITEST_MCP_QUEUE_TIMEOUT_SECONDS` | `30` | how long an MCP acquire waits for a free slot |

Rule of thumb: per replica, `SUITEST_RUNNER_CONCURRENCY` times the average
steps per run should stay under the per-workspace MCP session cap when most
runs target one workspace. Restart `api` and `runner` after editing `.env`.

## Auth model

Onboarding is closed by design:

- **Super-admin bootstrap.** Set `SUITEST_SUPERADMIN_EMAIL`,
  `SUITEST_SUPERADMIN_PASSWORD`, and optionally
  `SUITEST_SUPERADMIN_WORKSPACE_NAME` in `.env`. The account is created
  idempotently on API startup, and only if no users exist yet. Change the
  password after first login.
- **Invite-only after that.** There is no open signup. Existing members send
  invite links from Settings; invitations expire after 168 hours by default
  (`SUITEST_INVITE_TTL_HOURS`).
- **Optional Google OAuth.** Set `SUITEST_OAUTH_GOOGLE_CLIENT_ID` and
  `SUITEST_OAUTH_GOOGLE_CLIENT_SECRET` to enable it; it is only advertised
  when both are present.

## Artifact storage

Runs produce screenshots, videos, traces, and reports. All of it lands in the
S3 bucket, and the API serves downloads through presigned URLs, so the bucket
does not need to be publicly reachable beyond what the compose init job
configures. Budget storage accordingly: video evidence dominates, and the
bucket grows with run volume. See [Evidence](/docs/concepts/evidence/) for
what is stored per run.

## Reverse proxy and TLS

Terminate TLS in front of the stack and forward to the containers. With
Caddy, forwarding API, WebSocket, and SSE traffic to the API (port 4000) and
everything else to the web container (port 3000):

```text
suitest.example.com {
  reverse_proxy /api/* localhost:4000
  reverse_proxy /ws/*  localhost:4000
  reverse_proxy /sse/* localhost:4000
  reverse_proxy        localhost:3000
}
```

Remember `SUITEST_COOKIE_SECURE=true` once HTTPS is on, and set
`SUITEST_WEB_URL` / `SUITEST_API_URL` to the public URLs.

## Backups

| Layer | Strategy | Frequency |
|-------|----------|-----------|
| Postgres | `pg_dump --format=custom` to offsite object storage | every 6 hours |
| Postgres WAL | wal-g or pgbackrest streaming | continuous |
| MinIO artifacts | `mc mirror` to a remote bucket | every 24 hours |
| `SUITEST_ENCRYPTION_KEY` | sealed secret or external KMS, stored off-host | rotate at 90 days or more |

:::caution
Without the exact `SUITEST_ENCRYPTION_KEY`, restored LLM provider
configurations are unreadable. Back the key up separately from the database
dump, and never regenerate it casually on a live system.
:::

Restore drill (run it quarterly, not just when disaster strikes):

1. Provision a fresh host or namespace.
2. `pg_restore --clean --if-exists` the latest dump.
3. Mirror the artifact bucket back.
4. Apply the same `SUITEST_ENCRYPTION_KEY`.
5. Deploy the exact same Suitest version as the dump.
6. Smoke test: log in, open an old run, download an artifact.

## Upgrading

1. Read the changelog for breaking changes (data model, renamed variables).
2. Pull the new version and rebuild:
   `docker compose -f infra/docker/docker-compose.yml --profile zero up -d --build`.
3. The `migrate` service runs `alembic upgrade head` before the API starts,
   so schema migrations are automatic on boot.
4. Verify `/health` on the API and log in.

Roll back by checking out the previous version and restoring the matching
database backup; migrations are not guaranteed downgrade-safe pre-v1.0.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| API restart loop | `SUITEST_ENCRYPTION_KEY` has the wrong length | regenerate with `openssl rand -base64 32` |
| Config change has no effect | `.env` edited but services not restarted | `docker compose restart api runner` |
| Migration fails on external Postgres | pgvector extension missing | `CREATE EXTENSION IF NOT EXISTS vector;` as superuser |
| LOCAL-tier LLM calls time out | Ollama has not pulled the model | `docker compose exec ollama ollama pull <model>` |
| WebSocket disconnects behind a proxy | proxy read timeout too low | raise the proxy read timeout (for example 3600s) |

More in [Troubleshooting](/docs/help/troubleshooting/). For the quick local
variant of this setup, see the [Docker install](/docs/install/docker/).
