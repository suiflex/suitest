# Changelog

All notable Suitest milestone tags are listed here. Format: keepachangelog +
milestone groupings; the project follows semver-flavoured tags
``vMAJOR.MINOR.PATCH-<milestone>`` until 1.0.

## v0.4.0-m1c — M1c — Runner + MCP runtime complete (2026-05-29)

ZERO-tier runner + MCP runtime fully wired. Reproduces the full
``create → enqueue → execute → stream → artifact`` loop end-to-end against
the docker-compose stack.

### Added

- **packages/mcp** — generic async MCP client (stdio / SSE / WS / in-process
  transports), connection pool with LRU + TTL + per-provider lock, registry +
  routing table with workspace overrides, 60s health monitor with Redis
  pub/sub + auto-disable, invoker orchestrating pool + routing + audit +
  event publishing, workspace-level session cap with fair queue.
  (Tasks 1-5, 9, 21 — ROADMAP M1-16.)
- **Bundled MCP providers** — ``api-http-mcp`` (httpx + jsonpath assertions),
  ``playwright-mcp`` (stdio subprocess metadata + Docker bundling docs),
  ``postgres-mcp`` (in-process psycopg async with query / assert tools).
  (Tasks 6-8 — ROADMAP M1-17.)
- **apps/runner** — ARQ worker scaffold + lifecycle, step executor with
  code-parse + outcome decision tree, run orchestrator with per-step event
  stream + aggregation, artifact pipeline uploading to S3 / MinIO with DB
  rows. (Tasks 10-13 — ROADMAP M1-18 / M1-19.)
- **apps/api** — JWT-authenticated WebSocket gateway with run-room
  subscriptions + 30s heartbeat, ``POST /runs`` validating selection + MCP
  routing + enqueuing the ARQ job, ``POST /runs/:id/cancel`` +
  ``POST /runs/:id/rerun``, persisted run-step logs with cursor pagination +
  ``GET /runs/:id/logs``, ``GET /runs/:id/artifacts/:id`` returning a
  presigned S3 URL. (Tasks 14-18 — ROADMAP M1-19 / M1-20.)
- **apps/web** — Run detail page wired to the live WS stream
  (``RunSummaryCard`` + ``StepTable`` + ``LogPane`` + ``BrowserPreview``),
  MCP provider browser with health pill + tool list modal.
  (Tasks 19-20.)
- **DoD smoke E2E** — ``tests/e2e/test_m1c_smoke.py`` drives the full
  create-case → enqueue → WS subscribe → assert events → fetch artifact
  loop against the live compose stack. (Task 22.)

### Deferred

- Scheduled cron runs (ARQ cron) — moved to M1d per plan §"Scheduled cron"
  note. Original ROADMAP M1-20 scope was trimmed accordingly.

### Tag

Annotated tag ``v0.4.0-m1c``.

## v0.3.0-m1b — M1b — ZERO Frontend Read-only complete

App shell, capability boot, read-only screens (Dashboard, Test Cases, Runs,
Defects, Requirements, Analytics, Integrations, Inbox, Audit). See
``docs/superpowers/plans/2026-05-26-plan-03-m1b-frontend-readonly.md``.

## v0.2.0-m1a — M1a — Backend foundation + seed

FastAPI app, FastAPI-Users JWT auth, capability resolver, read endpoints
across the M1a surface, full Nusantara Retail seed. See
``docs/superpowers/plans/2026-05-26-plan-02-m1a-backend-foundation.md``.

## v0.1.0-m0 — M0 — Monorepo skeleton

Initial monorepo skeleton (apps/, packages/, infra/, docs/, pre-commit).
