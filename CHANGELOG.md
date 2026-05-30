# Changelog

All notable Suitest milestone tags are listed here. Format: keepachangelog +
milestone groupings; the project follows semver-flavoured tags
``vMAJOR.MINOR.PATCH-<milestone>`` until 1.0.

## v0.5.0-m1d — M1d — ZERO-mode closeout: manual TCM writes + integrations (2026-05-31)

Closes the ZERO tier. Full manual Test Case Management write surface,
soft-delete/restore, rule-based defect auto-filing, issue-tracker + webhook
integrations, and the frontend write UI — all deterministic, no LLM. 75
commits since ``v0.4.0-m1c``; every M1d-1..M1d-33 acceptance box green.

### Added — Backend writes

- **Manual TCM writes** — ``POST/PATCH /test-cases``, step replace/append/
  reorder, duplicate; ZERO-tier validator (``STEPS_REQUIRE_CODE_IN_ZERO_LLM``,
  ``MCP_PROVIDER_NOT_REGISTERED``); ``If-Unmodified-Since`` optimistic
  concurrency. (M1d-2)
- **Soft-delete + restore** for test cases, suites, projects, requirements;
  idempotent, tombstones excluded by default, ``?includeDeleted`` ADMIN-gated.
  (M1d-3..6)
- **Suite / Project / Requirement CRUD** — atomic ``case_order`` reorder,
  cascade soft-delete with ``confirmCascade`` guard, slug autogen, ``REQ-N``
  public ids, cross-workspace link guard. (M1d-4, M1d-5, M1d-6)
- **Bulk-update** ``POST /test-cases/bulk-update`` — delete/move/priority/
  tag-add/remove, 100-id cap, single transaction, no cross-workspace partial
  apply. (M1d-7)
- **Ad-hoc run shortcut** ``POST /test-cases/:id/run`` delegating to
  ``RunService``. (M1d-8)
- **Defects** — manual create/patch + status flow; rule-based
  ``DefectAutoFiler`` + regex ``DefectCategorizer`` (REGRESSION / FLAKE /
  ENVIRONMENT / TEST_BUG / MANUAL_TRIAGE) wired into the runner; partial-unique
  dedup index. (M1d-9, M1d-10)
- **Admin audit log** ``GET /audit-logs`` — cursor pagination + glob filters.
  (M1d-27)
- **Workspace settings** — General / Members / Danger-Zone delete. (M1d-28)

### Added — Integrations

- ``IssueTrackerAdapter`` Protocol + registry + contract test. (M1d-11)
- **Jira** (thin wrapper over bundled ``jirac-mcp@jira-mcp-v2.0.1``),
  **GitHub** (bundled ``github-mcp-server@v1.1.2``), **Linear** (httpx
  GraphQL, non-MCP), **Slack** (incoming-webhook + ARQ notification job).
  (M1d-12..15)
- **Webhook receivers** — GitHub (HMAC sha256 + gating-suite trigger + Redis
  dedup), GitLab (X-Gitlab-Token), Jira (issue_updated status sync-back).
  (M1d-16..18)
- **Integration CRUD** + test-connection + sync — AES-GCM at rest, no secret
  echo. (M1d-19)

### Added — Frontend

- ``<SplitGenerateButton>`` + ``<ManualCreateModal>``, ``<CaseEditor>`` route
  (RHF + Zod + dnd-kit + lazy Monaco), inline step editor, bulk-ops sticky
  action bar with optimistic updates. (M1d-20..22, M1-12)
- ``<Toaster>`` + ``undoToast`` wired to every soft-delete. (M1d-23)
- Interactive Defect cards, Integrations page (Connect/Configure/Disconnect +
  OAuth callback), "Run now" + gating-suite picker, admin audit-log virtualized
  table, workspace settings. (M1d-24..28)
- Cancel / Re-run buttons rewired to the M1c ``POST /runs/:id/{cancel,rerun}``
  endpoints; stale "ships in M1c" ``<DisabledTooltip>`` removed; VIEWER 403
  surfaces a capability banner. Defects "Open run" navigates to live run
  detail. (M1d-32, M1d-33)

### Added — Quality gates

- Auto-defect E2E (``test_auto_defect_e2e.py``). (M1d-29)
- Golden-path Playwright E2E (login → create case → run → PASS) + ``m1d-e2e``
  CI workflow; backend-agnostic interception, chromium project. (M1d-30)
- Visual-regression spec (``toHaveScreenshot``, baselines CI-generated) +
  loading/empty/error state audit across all 9 data screens. (M1d-31)

### Migration

- ``workspaces.strict_zero_validation`` (default TRUE),
  ``workspaces.mcp_routing_overrides``, ``suites.mcp_routing_overrides``.
- ``suites.deleted_at`` + ``ix_suites_project_active``;
  ``test_cases.order_in_suite``; ``projects.gating_suite_id``.
- ``mcp_providers.{command_pin, image_pin, version_pin, git_ref}``;
  ``workspace_id`` → nullable (bundled/global providers carry ``NULL``);
  ``enabled BOOLEAN NOT NULL DEFAULT 'true'``.
- ``uq_defects_auto_dedup`` partial unique index.
- Seed rows: ``jirac-mcp``, ``github-mcp`` (``workspace_id=NULL``,
  ``enabled=false`` until first connect).

### Notes

- First Jira/GitHub connect flips the bundled MCP ``enabled=true``.
- Run dedup uses Redis SETNX (no Postgres partial idx).
- All public ids via ``generate_public_id`` — no new global sequences.
- Bundled MCP binaries add ~45 MiB to the image (acceptable per
  ``DEPLOYMENT.md §15``).

### Tag

Annotated tag ``v0.5.0-m1d``.

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
