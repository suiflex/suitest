---
title: Environment variables
description: Every SUITEST_* environment variable by component, API, runner, MCP server, and CLI, with purposes and defaults.
---

All Suitest environment variables use the `SUITEST_` prefix. The API and the runner can share one `.env` file: runner-specific knobs use the `SUITEST_RUNNER_` prefix and fall back to the unprefixed variable where the two processes should agree (noted below).

:::note
**LLM providers are not configured via environment variables.** The provider and API key are set per workspace from the web UI (Settings, LLM) and stored AES-GCM encrypted. `SUITEST_LLM_*` variables appearing in tests are ignored by the platform. See [LLM setup](/docs/guides/llm-setup/).
:::

## API server

| Variable | Purpose | Default |
|---|---|---|
| `SUITEST_DATABASE_URL` | Postgres connection URL (asyncpg) | `postgresql+asyncpg://suitest:suitest@localhost:5432/suitest` |
| `SUITEST_REDIS_URL` | Redis URL (queue + pubsub) | `redis://localhost:6379/0` |
| `SUITEST_AUTH_SECRET` | Session/JWT signing secret (32-char random hex). Required. | none |
| `SUITEST_ENCRYPTION_KEY` | Base64 32-byte key for AES-GCM encryption of stored secrets (LLM keys, integration tokens). Required. | none |
| `SUITEST_S3_ENDPOINT` | Object storage endpoint (MinIO/S3) | `http://minio:9000` (compose) |
| `SUITEST_S3_BUCKET` | Artifact bucket | `suitest-artifacts` |
| `SUITEST_S3_ACCESS_KEY` | Object storage access key | `minioadmin` |
| `SUITEST_S3_SECRET_KEY` | Object storage secret key | `minioadmin` |
| `SUITEST_S3_REGION` | Object storage region | `us-east-1` |
| `SUITEST_S3_ARCHIVE_BUCKET` | Cold-storage bucket for archived audit logs and workspace exports | `suitest-archive` |
| `SUITEST_ARTIFACTS_BACKEND` | Artifact storage backend: `s3` or `local` (plain disk folder) | `s3` |
| `SUITEST_ARTIFACTS_DIR` | Artifact directory when the backend is `local` | `.suitest/artifacts` |
| `SUITEST_SUPERADMIN_EMAIL` | Super-admin bootstrap email, created idempotently on first startup when no users exist | empty (skip bootstrap) |
| `SUITEST_SUPERADMIN_PASSWORD` | Super-admin bootstrap password | empty |
| `SUITEST_SUPERADMIN_WORKSPACE_NAME` | Name of the bootstrap workspace | `Default Workspace` |
| `SUITEST_OAUTH_GOOGLE_CLIENT_ID` | Optional Google OAuth client id | empty |
| `SUITEST_OAUTH_GOOGLE_CLIENT_SECRET` | Optional Google OAuth client secret | empty |
| `SUITEST_COOKIE_SECURE` | Set `true` behind HTTPS so the session cookie is TLS-only | `false` |
| `SUITEST_WEB_URL` | Public URL of the web UI (links in notifications and PR comments) | `http://localhost:3000` |
| `SUITEST_API_URL` | Public URL of the API | `http://localhost:4000` |
| `SUITEST_EMBEDDINGS` | Local embeddings backend for semantic case search (e.g. `fastembed`); unset degrades to lexical search | unset |
| `SUITEST_EMBEDDINGS_BACKEND` | Embeddings backend selector | unset |
| `SUITEST_EMBEDDINGS_MODEL` | Embeddings model name (e.g. `BAAI/bge-small-en-v1.5`) | backend default |
| `SUITEST_AUDIT_LOG_RETENTION_DAYS` | Days audit-log rows stay in the hot table before rotation to cold storage | `365` |
| `SUITEST_EVAL_FIXTURES_DIR` | Fixture directory for eval runs | `eval/fixtures` |

The Docker Compose stack additionally uses `POSTGRES_PASSWORD` for the bundled Postgres service.

## Runner (ARQ worker)

Runner knobs read `SUITEST_RUNNER_*` first; where noted they fall back to the unprefixed variable so both processes stay in sync from one `.env`.

| Variable | Purpose | Default |
|---|---|---|
| `SUITEST_RUNNER_DATABASE_URL` (falls back to `SUITEST_DATABASE_URL`) | Postgres URL for the worker | same as API |
| `SUITEST_RUNNER_REDIS_URL` (falls back to `SUITEST_REDIS_URL`) | Redis URL for the ARQ queue | `redis://localhost:6379/0` |
| `SUITEST_RUNNER_CONCURRENCY` (legacy alias `SUITEST_RUNNER_MAX_JOBS_CONCURRENT`) | Jobs executed in parallel per worker process | `4` |
| `SUITEST_RUNNER_MAX_RETRIES` | Per-job retry budget on transient failure | `2` |
| `SUITEST_RUNNER_JOB_TIMEOUT_SECONDS` | Hard wall-clock budget for one `run_test_case` job | `1800` |
| `SUITEST_RUNNER_QUEUE_NAME` | ARQ queue name | `suitest:runs` |
| `SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE` (or `SUITEST_RUNNER_MCP_MAX_SESSIONS_PER_WORKSPACE`) | Per-workspace cap on concurrent MCP sessions across all providers | `16` |
| `SUITEST_MCP_QUEUE_TIMEOUT_SECONDS` (or `SUITEST_RUNNER_MCP_QUEUE_TIMEOUT_SECONDS`) | How long an MCP acquire may wait for a free slot before `MCP_POOL_EXHAUSTED` | `30` |
| `SUITEST_RUNNER_S3_ENDPOINT` (falls back to `SUITEST_S3_ENDPOINT`) | Object storage endpoint for artifact upload | `http://localhost:9000` |
| `SUITEST_RUNNER_S3_BUCKET` (falls back to `SUITEST_S3_BUCKET`) | Artifact bucket | `suitest-artifacts` |
| `SUITEST_RUNNER_S3_ACCESS_KEY` (falls back to `SUITEST_S3_ACCESS_KEY`) | Access key | `minioadmin` |
| `SUITEST_RUNNER_S3_SECRET_KEY` (falls back to `SUITEST_S3_SECRET_KEY`) | Secret key | `minioadmin` |
| `SUITEST_RUNNER_S3_REGION` (falls back to `SUITEST_S3_REGION`) | Region | `us-east-1` |
| `SUITEST_RUNNER_S3_ARCHIVE_BUCKET` (falls back to `SUITEST_S3_ARCHIVE_BUCKET`) | Cold-storage bucket | `suitest-archive` |
| `SUITEST_RUNNER_ARTIFACTS_BACKEND` (falls back to `SUITEST_ARTIFACTS_BACKEND`) | `s3` or `local` | `s3` |
| `SUITEST_RUNNER_ARTIFACTS_DIR` (falls back to `SUITEST_ARTIFACTS_DIR`) | Local artifact directory | `.suitest/artifacts` |
| `SUITEST_EVIDENCE_RECORDING` (or `SUITEST_RUNNER_EVIDENCE_RECORDING`) | Evidence mode: insert a small pause between steps so session video and per-step screenshots read as a timeline | `false` |
| `SUITEST_EVIDENCE_PAUSE_MS` (or `SUITEST_RUNNER_EVIDENCE_PAUSE_MS`) | Pause after each step in evidence mode (ms) | `700` |
| `SUITEST_RUNNER_AUDIT_LOG_RETENTION_DAYS` (falls back to `SUITEST_AUDIT_LOG_RETENTION_DAYS`) | Audit-log hot retention used by the rotation cron | `365` |
| `SUITEST_OTEL_DISABLED` | `true` / `1` / `yes` skips OpenTelemetry tracer setup | unset |

Production must override the MinIO dev credentials. See [Self-hosting](/docs/guides/self-hosting/).

## MCP server and lifecycle

These are set in the `env` block of your IDE's MCP config (`.mcp.json` or equivalent), or in the shell for CLI runs.

| Variable | Purpose | Default |
|---|---|---|
| `SUITEST_API_URL` | Suitest server URL. Required at MCP server startup together with the API key (validated against `GET /api/v1/api-keys/whoami`); the server refuses to start otherwise. | none |
| `SUITEST_API_KEY` | API key that pins the workspace/project every tool publishes into | none |
| `SUITEST_MODE` | `local` skips the startup credential gate and keeps results in on-disk storage instead of a server | unset (server mode) |
| `SUITEST_PYTHON` | Path to the Python >= 3.11 interpreter the npx launcher should use | first suitable `python` on `PATH` |
| `SUITEST_CONFIG_DIR` | Directory for saved launcher credentials (`credentials.json`) | `~/.config/suitest` |
| `SUITEST_RECREATE_PROJECT` | `1` / `true` behaves like `publish.recreateProject`: explicit opt-in to recreate a stale project binding | unset |
| `SUITEST_EVIDENCE_SLOWMO_MS` | Slow-motion delay injected into generated frontend tests in evidence mode (ms) | `300` |

## Platform CLI

| Variable | Purpose | Default |
|---|---|---|
| `SUITEST_API_URL` | API base URL (overridden by `--api-url`) | `http://localhost:4000` |
| `SUITEST_TOKEN` | Bearer token (overridden by `--token`) | none |
| `SUITEST_WORKSPACE_ID` | Workspace id sent as `X-Workspace-Id` (overridden by `--workspace`) | none |

See the [CLI reference](/docs/reference/cli/) for the flags these back.

:::tip
Minimal production checklist: `SUITEST_AUTH_SECRET`, `SUITEST_ENCRYPTION_KEY`, `SUITEST_DATABASE_URL`, `SUITEST_REDIS_URL`, the `SUITEST_S3_*` set with real credentials, `SUITEST_COOKIE_SECURE=true`, and the super-admin pair for first login.
:::
