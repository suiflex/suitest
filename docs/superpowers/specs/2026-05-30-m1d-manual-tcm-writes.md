# M1d — Manual TCM writes, rule-based defects, integration adapters (ZERO mode closeout)

## Goal
Close the remaining ZERO-tier acceptance criteria in M1 (#M1-12 → #M1-15, #M1-21 → #M1-27) so a self-host user on `SUITEST_LLM_PROVIDER=none` can fully author, edit, soft-delete, bulk-mutate, run, and triage cases, with rule-based auto-defect filing and external tracker/notification adapters. Tier: **ZERO only** — no LiteLLM, no LangGraph, no `require_tier(LOCAL|CLOUD)` introduced. After M1d the ZERO deploy is the "TestRail + Playwright replacement" promised in `docs/PRODUCT.md` and `docs/ROADMAP.md` M1 DoD, and M2 (generators + MCP expansion) becomes unblockable.

Why now: M1a shipped read-only REST, M1b shipped read-only UI, M1c (commits `828dace…e464c9d`) shipped the runner, run lifecycle, WS streaming, MCP routing, MinIO artifacts and the workspace MCP session cap. The only `[ ]` left in `docs/ROADMAP.md#M1` are write-side TCM, defect filing, integrations, and the M1-28/29/30 quality bar. M1d delivers that.

## In scope

- **Test case + step writes** — `POST /test-cases`, `PATCH /test-cases/:id`, `PATCH /test-cases/:id/steps` (atomic replace), `POST /test-cases/:id/steps` (append), `DELETE /test-cases/:id` (soft) + `POST /test-cases/:id/restore`, `POST /test-cases/:id/duplicate`, `POST /test-cases/:id/run` (ad-hoc). All validate `STEPS_REQUIRE_CODE_IN_ZERO_LLM` and `MCP_PROVIDER_NOT_REGISTERED` per `docs/API.md`.
- **Suite + project CRUD** — incl. `case_order` reorder, `confirmCascade` flag, ADMIN/OWNER gate for projects.
- **Requirement + link CRUD** — `REQ-N` public id, `(requirement_id, case_id)` link, cross-workspace 400.
- **Bulk endpoint** — `POST /test-cases/bulk-update` for delete / move-to-suite / change priority / add+remove tags, 100-id cap, single transaction.
- **Defects** — manual `POST /defects`, `PATCH /defects/:id` status flow (OPEN → IN_PROGRESS → RESOLVED → CLOSED → WONT_FIX), `POST /defects/:id/sync-external`. Plus **`DefectAutoFiler`** wired into the M1c `on_run_step_failed` runner hook with a regex `DefectCategorizer` covering REGRESSION / FLAKE / INFRA / SPEC_DRIFT / MANUAL_TRIAGE fallback, severity by case priority, dedup via partial unique index on `(run_id, test_case_id) WHERE created_by='system'`.
- **Integration adapter Protocol** (`packages/agent`-style: `apps/api/src/suitest_api/integrations/`) — `IssueTrackerAdapter` Protocol + registry + contract test, then concrete `JiraAdapter` (**thin wrapper over bundled `jirac-mcp` MCP server** — owns OAuth 3LO + cloudId discovery + AES-GCM token storage; tool execution delegated via `packages/mcp/client` to avoid duplicating Jira REST client; see § "MCP-native integration shift"), `LinearAdapter` (PAT + GraphQL `issueCreate` — stays httpx for v1.0 unless `linear-mcp` adopted), `GitHubAdapter` (App installation token — stays httpx for v1.0), `SlackAdapter` (incoming webhook — httpx). `JiraAdapter` test via mocked MCP session (`packages/mcp/client` test double), others via `respx` + VCR cassette. All non-MCP HTTP through one `httpx.AsyncClient` with `timeout=10s` + connection pool.
- **Webhook receivers** — `POST /webhooks/github` (HMAC sha256, push + PR opened/sync/reopened), `POST /webhooks/gitlab` (X-Gitlab-Token), `POST /webhooks/jira` (issue_updated status sync). Per-workspace secret lookup, constant-time compare, 60-second dedup partial index on `(project_id, commit_sha, trigger)`.
- **Integration CRUD** — `POST/PATCH/DELETE /integrations/:id` with AES-GCM secret encryption via `packages/core/crypto` (already exists), `POST /integrations/:id/test`, `POST /integrations/:id/sync`. Secrets never echoed in `IntegrationRead`.
- **Frontend writes** — Cases list `<SplitGenerateButton>` (Manual enabled; Recorder/OpenAPI/Crawler disabled with M2 tooltip; "Generate with AI" disabled with `<Gated feature="ai_generation">` upgrade hint per CLAUDE §4), `<ManualCreateModal>`, full `<CaseEditor>` route with React Hook Form + Zod + `@dnd-kit/sortable` reorder + **lazy-loaded** `@monaco-editor/react` for `step.code`, `Cmd+S` save, optimistic updates with rollback, unsaved-changes guard, `If-Unmodified-Since` 409 conflict detection.
- **FE defects/integrations/run trigger/bulk/undo** — interactive defect cards, sonner `<Toaster>` with 8s undo toast on soft-delete, "Run now" button on case detail, gating-suite picker dialog on Dashboard, integrations page connect/configure/disconnect with OAuth callback route.
- **Workspace admin** — Audit log UI (admin-only route, virtualized table, filters), workspace settings General / Members / Danger Zone (slug-type-to-confirm deletion).
- **Migrations** — `add_public_id_sequences`, `add_workspace_settings.strict_zero_validation`, `add_suite_order.order_in_suite`, `runs_dedup` partial idx, `defects_auto_dedup` partial idx, `projects_gating_suite_id` (nullable FK). All idempotent, `downgrade()` round-trip tested.
- **M1 quality bar** — `M1-28` golden-path Playwright E2E (login → create case → run via MCP → see result), `M1-29` visual-regression ≥95% for Cases edit + Defects + Integrations vs `Suitest.html` mockup, `M1-30` loading/empty/error states audit.
- **Auto-defect E2E** — `apps/api/tests/e2e/test_auto_defect_e2e.py` proves runner → fail → categorize → persist → Jira mock → Slack mock chain green.

## Out of scope (deferred to M2 or later)

- Any LLM call, LangGraph, LiteLLM, AI categorizer, AI panel chat (M3).
- Deterministic generators (OpenAPI / Recorder / URL crawler) — split-button items stay **disabled with `<DisabledTooltip reason="Available in M2">`** (M2-1..3).
- Custom MCP registration UI / MCP tool browser / mixed-MCP E2E demo (M2-6..11).
- Test code export `?target=playwright|cypress|selenium` (M2-12).
- Scheduled cron runs (already deferred from `M1-20`, picked up in M2 or M5).
- `WebhookRetryQueue` + audit log archival + workspace export/import (M4-29..32).
- Slack OAuth app w/ interactive buttons — webhook-only in M1d (revisit M5).
- Hard-delete background job for soft-deleted rows — column lands, sweeper deferred.
- Embeddings / pgvector wiring — `none` backend per `CAPABILITY_TIERS.md` ZERO row.

## Acceptance criteria (DoD)

Each box = one squash-merged PR per CLAUDE §6 / ROADMAP cross-cutting rule.

- [ ] **M1d-1** Migrations land + Alembic round-trip test green (`add_public_id_sequences`, `strict_zero_validation`, `order_in_suite`, `runs_dedup`, `defects_auto_dedup`, `projects_gating_suite_id`). Also seeds **bundled `jirac-mcp` row** into `mcp_providers` (`kind=issue-tracker`, `command_pin=jirac-mcp@<pinned>`, `transport=stdio`, `enabled=false` by default — flipped on once integration is connected).
- [ ] **M1d-2** Test case writes: `POST /test-cases` + `PATCH /test-cases/:id` (metadata + tag replace) + `PATCH /test-cases/:id/steps` (atomic replace) + `POST /test-cases/:id/steps` (append, `SELECT MAX(order) FOR UPDATE`) + `POST /test-cases/:id/duplicate`. ZERO `STEPS_REQUIRE_CODE_IN_ZERO_LLM` error returns `details.stepIndex`. Cross-workspace = 404, never 403. (Closes #M1-12)
- [ ] **M1d-3** Soft delete + restore: `DELETE /test-cases/:id` (204, idempotent re-DELETE → 404), `POST /test-cases/:id/restore`, list excludes `deleted_at IS NOT NULL` by default. (Closes #M1-13 part)
- [ ] **M1d-4** Suite CRUD with `case_order` reorder + `confirmCascade=true` cascade soft-delete; `POST /suites/:id/restore`. (Closes #M1-13)
- [ ] **M1d-5** Project CRUD ADMIN/OWNER-gated with slug autogen + cascade-confirm. (Closes #M1-13)
- [ ] **M1d-6** Requirement CRUD + Link CRUD with `CROSS_WORKSPACE_LINK` 400. `REQ-N` public id sequence. (Closes #M1-24, supports #M1-25)
- [ ] **M1d-7** `POST /test-cases/bulk-update` (delete / suite move / priority / tag add+remove), 100-id cap, single transaction, one audit row per case. (Closes #M1-15)
- [ ] **M1d-8** `POST /test-cases/:id/run` ad-hoc shortcut delegates to M1c `RunService.create`, pre-flight re-validates `STEPS_REQUIRE_CODE_IN_ZERO_LLM`, returns `{runId, publicId, statusUrl, wsRoom}`. (Closes #M1-20 ad-hoc path)
- [ ] **M1d-9** Defects: manual `POST /defects` (`SUIT-N`), `PATCH /defects/:id` status flow with `resolved_at` flip, `POST /defects/:id/sync-external`. (Closes #M1-23)
- [ ] **M1d-10** `DefectAutoFiler` + regex `DefectCategorizer` wired into runner `on_run_step_failed` hook from M1c task 12. Dedup partial unique index. ≥1 test per rule. Severity from case priority. Emits WS `defect.created` exactly once. (Closes #M1-21)
- [ ] **M1d-11** Integration adapter Protocol + registry + contract test in `apps/api/src/suitest_api/integrations/`. Zero concrete adapters registered makes contract test pass with 0 iterations.
- [ ] **M1d-12** `JiraAdapter` thin wrapper over `jirac-mcp` — owns OAuth 3LO (`/integrations/jira/connect` + `/integrations/jira/oauth-callback`), `accessible-resources` → cloudId discovery, refresh-token flow, AES-GCM token storage. Tool execution (`create_issue`, `update_issue`, `transition`, `search`) delegates to `mcp.client.invoke("jirac-mcp", "<tool>", args)`. Status + severity maps Python-side. Test via mocked MCP session (no `respx`). Bundled `jirac-mcp` binary in main image per `docs/DEPLOYMENT.md §15`.
- [ ] **M1d-13** `LinearAdapter` (PAT, `issueCreate` GraphQL, state-name → DefectStatus map, severity → priority 1..4).
- [ ] **M1d-14** `GitHubAdapter` (App installation token mint + 50-min cache, `severity:<low>` label).
- [ ] **M1d-15** `SlackAdapter` (incoming webhook, blocks + severity color, `test_connection`). Wired to `DefectAutoFiler` arq job `send_slack_notification` with exponential retry. (Closes #M1-27 Slack)
- [ ] **M1d-16** `POST /webhooks/github` HMAC sha256 constant-time verify, push + PR opened/sync/reopened, `ping → 200`, gating suite via `project.gating_suite_id` else `smoke`-tagged cases, 60s dedup. (Closes #M1-27 CI/CD)
- [ ] **M1d-17** `POST /webhooks/gitlab` X-Gitlab-Token verify + push + MR scaffolding.
- [ ] **M1d-18** `POST /webhooks/jira` issue_updated status sync → local defect status via `JiraAdapter.map_external_status_to_defect_status` + audit `defect.status_synced_from_jira`. (Closes #M1-22 sync-back)
- [ ] **M1d-19** Integration CRUD + `POST /integrations/:id/test` + `POST /integrations/:id/sync`, secrets via AES-GCM, `IntegrationRead` never returns secret material. ADMIN/OWNER gated. (Closes #M1-22)
- [ ] **M1d-20** FE `<SplitGenerateButton>` + `<ManualCreateModal>` (Manual enabled; Recorder/OpenAPI/Crawler disabled w/ M2 tooltip; AI option wrapped in `<Gated feature="ai_generation">`).
- [ ] **M1d-21** FE `<CaseEditor>` route — RHF+Zod + `useFieldArray` + `@dnd-kit/sortable` reorder + lazy `<MonacoCodeEditor>` (Suspense fallback `<TextareaPlaceholder/>`) + `Cmd/Ctrl+S` save + `useBlocker` unsaved guard + `If-Unmodified-Since` 409 conflict toast.
- [ ] **M1d-22** FE bulk-ops sticky action bar + multi-select column + optimistic update + rollback. (Closes #M1-15 FE)
- [ ] **M1d-23** FE `<Toaster richColors closeButton position="bottom-right">` + `undoToast` helper wired to case/suite/project/requirement deletes. (Closes #M1-13 FE)
- [ ] **M1d-24** FE Defect cards interactive: status combobox, assignee picker, severity edit, "Sync to tracker" button, filter chips + "auto-filed only" toggle. (Closes #M1-23 FE)
- [ ] **M1d-25** FE Integrations page Connect/Configure/Disconnect per kind + OAuth callback route at `/integrations/oauth-callback` + "Set as default tracker" toggle.
- [ ] **M1d-26** FE "Run now" button on case detail + gating-suite picker dialog on Dashboard, both with success-toast deep-link to `/runs/:id`.
- [ ] **M1d-27** Admin audit log UI virtualized table at `/settings/audit` + `GET /audit-logs` cursor pagination with action-glob filter (verify or add in API).
- [ ] **M1d-28** Workspace settings — General + Members invite/remove + Danger Zone (type-slug confirmation, `DELETE /workspaces/:id` OWNER-only).
- [ ] **M1d-29** E2E `apps/api/tests/e2e/test_auto_defect_e2e.py` — testcontainers PG seed → ad-hoc run → step fails on row-count assertion → defect auto-filed REGRESSION → mock Jira receives POST → mock Slack receives POST. Gates the milestone.
- [ ] **M1d-30** Golden-path Playwright E2E in CI: login → create case → "Run now" → see result. (Closes #M1-28)
- [ ] **M1d-31** Visual-regression ≥95% match for Cases edit / Defects / Integrations vs `Suitest.html`. Loading/empty/error states audited per screen. (Closes #M1-29, #M1-30)
- [ ] **M1d-32** Tag `v0.5.0-m1c+1` → release notes + CHANGELOG.md entry → tag `v0.5.0-m1d` after all boxes green.

DoD: `SUITEST_LLM_PROVIDER=none` deploy authors cases via Monaco editor, runs them through M1c MCP runner, sees rule-based auto-defect filed to Jira mock + Slack mock, traceability matrix from M1a/M1b still green. **Zero LLM calls ever made.**

## Architecture / data model touchpoints

- **New module** `apps/api/src/suitest_api/integrations/` — `base.py` (`IssueTrackerAdapter` Protocol, `ExternalIssue`, `ExternalIssueInput`), `registry.py` (`AdapterRegistry`), `jira_adapter.py` (delegates to `packages/mcp/client` → `jirac-mcp`), `linear_adapter.py` (httpx GraphQL), `github_adapter.py` (httpx REST), `slack_adapter.py` (httpx webhook). Registered in `apps/api/src/suitest_api/main.py` lifespan.
- **Bundled MCP provider** `jirac-mcp` registered in `packages/mcp/suitest_mcp/bundled/jira.py` (declarative config: `command="jirac-mcp"`, `transport=stdio`, env injection contract for `JIRA_HOST`/`JIRA_TOKEN`). Token passed per-invocation via `pool.acquire(provider, env_overrides={...})` — never written to `~/.config/jira/config.toml`. `docs/MCP_PLUGINS.md §3` bundled table gets new row: `jirac-mcp | issue-tracker | stdio | EXTERNAL_TOOL | Issue tracker integration | cloud-token / PAT`. `docs/ARCHITECTURE.md` integration-vs-MCP layer split clarified: external **action** (file issue, transition) goes through MCP; OAuth handshake + secret storage stay in API service.
- **New module** `apps/api/src/suitest_api/services/defect_auto_filer.py` (`DefectAutoFiler`, `DefectCategorizer`, `_RULES`, `_SEVERITY_BY_PRIORITY`, `CategorizedDefect`). Runner DI in `apps/runner/src/suitest_runner/deps.py` exposes it; `apps/runner/src/suitest_runner/handlers/step_handler.py` invokes `file_for_failed_step(run_step.id)` on `StepOutcome.FAIL`.
- **New module** `apps/api/src/suitest_api/webhooks/` (or extend routers/) — `github.py`, `gitlab.py`, `jira.py`, with shared `WebhookReceiver` service.
- **Validator** `apps/api/src/suitest_api/services/test_case_validator.py` houses `validate_steps(steps, tier, workspace_settings, registered_mcp_names)` reused by create / replace / append / ad-hoc-run pre-flight.
- **Existing services extended** — `test_case_service.py`, `suite_service.py`, `project_service.py`, `requirement_service.py`, `defect_service.py`, `integration_service.py` get write methods; reuse `RunService` from M1c.
- **Shared schemas** added per entity under `packages/shared/suitest_shared/schemas/` (test_case, suite, project, requirement, defect, integration, webhooks_github, webhooks_gitlab). Matching Zod schemas under `packages/shared/src/schemas/` (manual mirror until M4 codegen).
- **DB columns / sequences added** — `workspaces.strict_zero_validation BOOLEAN DEFAULT TRUE`, `test_cases.order_in_suite INTEGER DEFAULT 0`, `projects.gating_suite_id UUID NULL`, sequences `test_case_public_seq`, `defect_public_seq`, `requirement_public_seq`, `run_public_seq`. Partial unique idx `uq_defects_auto_dedup ON defects(run_id, test_case_id) WHERE created_by='system'`. Partial unique idx `ix_runs_dedup_recent ON runs(project_id, commit_sha, trigger) WHERE created_at > NOW() - INTERVAL '60 seconds'`. (Confirm against `docs/DATA_MODEL.md §11` — see Open Questions.)
- **Audit log** — every write hits `packages/db/audit.py` with `(workspace_id, user_id, action, resource_type, resource_id, metadata)`; no UPDATE/DELETE endpoint on `audit_logs`.
- **Crypto** — `Integration.secrets_encrypted` and webhook secret via existing `packages/core/crypto.aes_gcm_encrypt`. Master key from `SUITEST_ENCRYPTION_KEY` env, 32-byte base64, validated at app startup.
- **WS events** added: `case.created`, `case.updated`, `case.steps.replaced`, `defect.created`, `defect.updated`, `integration.error`. Emitted to room `workspace:{workspaceId}` through existing M1b WS gateway.

## MCP / capability gating implications

- **All M1d endpoints are ZERO-compatible** — none introduces `Depends(require_tier(Tier.CLOUD | Tier.LOCAL))`. Per CLAUDE §4 "Test ZERO mode dulu", smoke matrix runs with `SUITEST_LLM_PROVIDER=none`.
- **Role gating, not tier gating, is the new lever** — `Depends(require_role({Role.QA, Role.ADMIN, Role.OWNER}))` on case/suite/requirement writes; `Depends(require_role({Role.ADMIN, Role.OWNER}))` on project + integration + audit; `OWNER` only on workspace danger zone.
- **AI surfaces stay hidden** in the FE — `<Gated feature="ai_generation">` wraps the "Generate with AI" split-button item (returns `<UpgradeHint>` in ZERO per `CAPABILITY_TIERS.md`). AI Panel from M1b stays hidden via `<Gated feature="ai_panel">`. Tier badge shows `ZERO`.
- **MCP invariant preserved** — every `Step` written via the new endpoints carries `mcp_provider` + `target_kind`. Validator rejects unregistered providers with `MCP_PROVIDER_NOT_REGISTERED` (404). The ad-hoc run shortcut, the auto-defect runner hook, and the webhook-enqueued runs all flow through `packages/mcp/client` from M1c — no direct MCP invocation in API routes.
- **Workspace-level MCP session cap from M1c** is reused — bulk-trigger of webhook-driven runs respects the fair queue; no new concurrency primitives.
- **No LLM call surface**: `DefectCategorizer` is regex; defect title/description are templated strings; no `packages/agent` import touched in M1d. `agent_diagnosis_kind` enum values `REGRESSION/FLAKE/INFRA/SPEC_DRIFT/MANUAL_TRIAGE` are assigned by rules, not LLM, with `created_by='system'` distinguishing from M3-future AI diagnoses.

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| OAuth 3LO secret-storage + refresh-token race across worker pods | M | Single source-of-truth row in `integrations` table; `_ensure_token` uses `SELECT ... FOR UPDATE` on the integration row when refreshing; cache token in-process keyed by `(workspace_id, kind)` with 50-min TTL. |
| `jirac-mcp` upstream breakage (Rust binary, fast-moving) | M | `command_pin` per `MCP_PLUGINS.md §13`; CI runs smoke suite tagged `mcp:jirac` against pinned version on every Suitest release; upstream is `mulhamna/jira-commands` (same author org) → tight feedback loop. Fallback: feature-flag `SUITEST_JIRA_MODE=mcp\|httpx` lets users pin to legacy httpx adapter if upstream stalls. |
| `jirac-mcp` tool schema drift between minor versions | M | At provider registration time, persist discovered `tools/list` JSON schema (`MCP_PLUGINS.md §5.3 step 4`); compare on upgrade; reject if breaking change. |
| Rust binary bloat air-gapped image | L | Multi-stage Docker build, vendored crates cache; size budget +20 MB. Acceptable per `DEPLOYMENT.md §15`. |
| OAuth 3LO not supported in `jirac-mcp` (currently cloud-token + PAT only) | M | Suitest API service handles 3LO browser redirect + `accessible-resources` cloudId lookup + token storage; passes resulting `JIRA_TOKEN` to `jirac-mcp` per-invocation env. Long-term: upstream PR to add 3LO to `jirac-mcp` itself. |
| Auto-defect double-file when runner retries a step (transient crash) | M | Partial unique index `uq_defects_auto_dedup` + `DefectAutoFiler.file_for_failed_step` returns `None` on conflict. Manual defect on same `(run, case)` still allowed because partial idx scopes `created_by='system'`. |
| Webhook flood causes Jira/Linear rate-limit cascade | M | ARQ external-issue job has workspace-level concurrency cap of 4; httpx `timeout=10s`; ARQ retry 5x exp backoff; on terminal fail mark integration `status=error` + emit WS `integration.error`. Hardening via M4-31 `WebhookRetryQueue` deferred. |
| Atomic step replace breaks under concurrent author edits | M | `SELECT ... FOR UPDATE` on `test_cases` row inside transaction + `If-Unmodified-Since` precondition header → 409 `CONCURRENT_MODIFICATION`. Vitest covers conflict toast UX. |
| Monaco editor balloons FE bundle (Vite chunking) | M | `lazy(() => import("@monaco-editor/react"))` + `<Suspense fallback={<TextareaPlaceholder/>}>`. CI assertion: `pnpm build --analyze` Monaco chunk not in initial vendor bundle. |
| Bulk endpoint mis-tenants 100 ids across workspaces | L | Validator pre-checks every id against `workspace_id` — mixed-workspace ids return 403 with offending id list; never partial-apply. |
| HMAC timing oracle on webhook receivers | L | `hmac.compare_digest` exclusively; unsigned requests = 401; per-workspace secrets so one tenant's secret can't replay another's. |
| Soft-delete leaves linked defects orphaned visually | L | Defects keep `test_case_id` FK; FE shows `(deleted)` decoration; `includeDeleted=true` admin query param surfaces deleted rows. |
| OAuth callback CSRF | L | State token in signed cookie generated at `/integrations/jira/connect`; callback verifies before code exchange (same for GitHub App install). |
| FE optimistic UI silently drifts from server | L | TanStack Query `onError` rollback + `onSettled` invalidate; every mutation paired with a toast; WS `case.updated` triggers refetch of any open editor. |
| Monaco a11y / keyboard reorder regressions | L | dnd-kit keyboard sensor on grip handle; `accessibilitySupport: "on"` Monaco option; axe smoke check in Vitest. |
| Visual-regression CI flake against `Suitest.html` baseline | M | Pin Percy/playwright-visual threshold to 95% per `M1-29`; allow per-screen override file; CI uploads diff artifacts when fail. |

## Suggested PR breakdown

One acceptance criterion per PR per CLAUDE §6 + ROADMAP cross-cutting. Suggested order (parallelizable groups in brackets):

1. **PR-1 → M1d-1** — Alembic migrations (sequences, `strict_zero_validation`, `order_in_suite`, gating_suite_id, dedup indices) + round-trip test.
2. **PR-2 → M1d-2** — `POST/PATCH /test-cases` + `validate_steps` + atomic step replace + append + duplicate + tag normalization. Pytest matrix per `STEPS_REQUIRE_CODE_IN_ZERO_LLM`, cross-tenant 404, concurrency. *(Depends PR-1.)*
3. **PR-3 → M1d-3** — soft delete + restore + list filter + audit. *(Depends PR-2.)*
4. **PR-4 → M1d-4** — Suite CRUD + reorder + cascade.
5. **PR-5 → M1d-5** — Project CRUD ADMIN/OWNER gated.
6. **PR-6 → M1d-6** — Requirement + Link CRUD.
7. **PR-7 → M1d-7** — `POST /test-cases/bulk-update` + 100-id cap + single-transaction service.
8. **PR-8 → M1d-8** — `POST /test-cases/:id/run` delegating to `RunService`.
9. **PR-9 → M1d-9** — Manual defect endpoints + sync-external.
10. **PR-10 → M1d-10** — `DefectAutoFiler` + categorizer + runner hook wiring + dedup constraint + runner integration test.
11. **PR-11 → M1d-11** — `IssueTrackerAdapter` Protocol + registry + contract test scaffold. *(Independent — parallel with PR-2..10.)*
12. **PR-12 → M1d-12** — Jira adapter (OAuth 3LO + cloudId + status map) **as thin wrapper over bundled `jirac-mcp`**. Also lands `packages/mcp/suitest_mcp/bundled/jira.py`, updates `docs/MCP_PLUGINS.md §3` table, updates `docs/DEPLOYMENT.md §15` air-gap bundle list, and adds `Dockerfile` stage to bundle `jirac-mcp` Rust binary into main image. *(After PR-11.)*
13. **PR-13 → M1d-13** — Linear adapter (PAT + GraphQL).
14. **PR-14 → M1d-14** — GitHub adapter (App installation token).
15. **PR-15 → M1d-15** — Slack adapter + `send_slack_notification` ARQ job wired to `DefectAutoFiler`.
16. **PR-16 → M1d-16** — GitHub webhook receiver + HMAC + gating-suite selector + 60s dedup idx.
17. **PR-17 → M1d-17** — GitLab webhook scaffolding.
18. **PR-18 → M1d-18** — Jira webhook status sync-back.
19. **PR-19 → M1d-19** — Integration CRUD + test + sync (secrets redaction).
20. **PR-20 → M1d-20** — FE `<SplitGenerateButton>` + `<ManualCreateModal>`. *(Depends PR-2.)*
21. **PR-21 → M1d-21** — FE `<CaseEditor>` + Monaco lazy + dnd-kit + RHF/Zod + `If-Unmodified-Since` 409 toast. *(Depends PR-2..3.)*
22. **PR-22 → M1d-22** — FE bulk-ops sticky bar + optimistic. *(Depends PR-7, PR-21.)*
23. **PR-23 → M1d-23** — FE `undoToast` + sonner + wire to all soft-deletes.
24. **PR-24 → M1d-24** — FE Defect cards interactive + filter chips. *(Depends PR-9.)*
25. **PR-25 → M1d-25** — FE Integrations Connect/Configure/Disconnect + OAuth callback route. *(Depends PR-12..15, PR-19.)*
26. **PR-26 → M1d-26** — FE "Run now" + gating-suite picker. *(Depends PR-8.)*
27. **PR-27 → M1d-27** — Admin audit log UI + `GET /audit-logs` filters.
28. **PR-28 → M1d-28** — Workspace settings (General/Members/Danger).
29. **PR-29 → M1d-29** — E2E `test_auto_defect_e2e.py` (testcontainers + mock Jira/Slack).
30. **PR-30 → M1d-30** — Playwright golden-path E2E in CI.
31. **PR-31 → M1d-31** — Visual-regression baselines + loading/empty/error pass.
32. **PR-32 → M1d-32** — CHANGELOG + tag `v0.5.0-m1d`.

Parallel-safe clusters: {PR-4, PR-5, PR-6, PR-11} after PR-1; {PR-12, PR-13, PR-14, PR-15} after PR-11; {PR-17, PR-18} after PR-16; {PR-23, PR-24, PR-26, PR-27} after their backend deps. PR-29 is the final gate before tag.

## MCP-native integration shift (added 2026-05-30)

Per `docs/MCP_PLUGINS.md §1` — "Every step that touches an external system goes through an MCP server" — M1d's `JiraAdapter` was reframed to use the bundled `jirac-mcp` server (`mulhamna/jira-commands`) for all tool execution instead of duplicating Jira REST in Python `httpx`.

| Concern | Owner |
|---------|-------|
| OAuth 3LO + cloudId discovery + token storage | Python `JiraAdapter` (thin) |
| AES-GCM secret encryption | `packages/core/crypto` (existing) |
| Token injection into MCP session | `pool.acquire(provider, env_overrides={JIRA_HOST, JIRA_TOKEN})` |
| `create_issue / update / transition / search` | `jirac-mcp` via `packages/mcp/client` |
| Webhook receivers (`POST /webhooks/jira`) | Python — inbound, MCP doesn't help |
| Status map (Jira workflow → `DefectStatus`) | Python `_map_status` helper |

`LinearAdapter`, `GitHubAdapter`, `SlackAdapter` stay httpx for M1d. Linear-MCP / GH-MCP adoption deferred to M2 (open question 11 below).

## Open questions for the user

1. **`DiagnosisKind` enum exact set** — the M1d plan-05 reference uses `REGRESSION / FLAKE / INFRA / SPEC_DRIFT / MANUAL_TRIAGE`, while `docs/superpowers/specs/2026-05-26-…-pivot-design.md §4` AUTONOMY table names `FLAKE / REGRESSION / ENVIRONMENT / TEST_BUG`. **Which is canonical in `docs/DATA_MODEL.md`?** Please confirm before PR-10 so the migration ships the right enum values (SPEC_DRIFT vs TEST_BUG, INFRA vs ENVIRONMENT). I will not invent — flag blocker on PR-10 if unanswered.
2. **`STEPS_REQUIRE_CODE_IN_ZERO_LLM` strictness default** — pivot memo §10 says "optional saat workspace setting strict=true". Should `workspaces.strict_zero_validation` default `TRUE` (safer; matches plan-05) or `FALSE` (more lenient for action-only authoring + future tier-upgrade)? Defaulting `TRUE` for v1.0 unless told otherwise.
3. **GitHub App vs PAT for `GitHubAdapter`** — plan-05 picks GitHub App (richer, but requires `SUITEST_GITHUB_APP_*` env + install URL). Is the GitHub App route acceptable for v1.0 self-host, or should v1.0 ship PAT-based Issues for simpler ZERO setup with App deferred to M5? Affects deployment docs in `docs/DEPLOYMENT.md`.
4. **Gating-suite fallback semantics** — when project has neither `gating_suite_id` nor any `smoke`-tagged case, do we return `200 { ignored: true }` (plan-05) or `400 NO_GATING_SUITE` (stricter, visible-error)? Webhook UX implication.
5. **`tier_at_runtime` column on `runs`** — plan-05 task 1g references it but DATA_MODEL needs verification. If absent, add to migration PR-1 or drop the snapshot field; I will not invent the column.
6. **Public id format collision with seed** — `M1a-9` seed builds `Nusantara Retail` with N cases already at `TC-…`. Sequence start value needs alignment so seeded ids don't collide with newly-authored ids. Confirm preferred sequence min-value (e.g., `START WITH 10000`).
7. **Bulk endpoint role gate** — should bulk `delete` require ADMIN/OWNER or QA+? Plan-05 implies QA+ since case CRUD is QA+; confirm before PR-7.
8. **`docs/UI_SPEC.md` "Run now" placement** — pivot memo §11 has Generation modal but does not call out the case-detail "Run now" location explicitly. Use top-right action toolbar (plan-05) or row-level icon? Default: top-right action toolbar; flag if `docs/UI_SPEC.md` says otherwise.
9. **Slack adapter `test_connection` payload visibility** — posting a "Suitest connection test" to the configured channel is intrusive. Acceptable for v1.0, or use Slack's `chat.scheduleMessage` dry-run? Defaulting to intrusive test message with confirm dialog in UI.
10. **Visual-regression baseline owner** — `Suitest.html` is read-only and slated for deletion when M1-29 ≥95% match (CLAUDE §1 note). After M1d hits 95%, do we delete `Suitest.html` immediately or wait for M2's generator UI completeness? Default: keep through M2.
11. **`jirac-mcp` OAuth 3LO support** — currently `jirac-mcp` accepts Jira Cloud API token + Data Center PAT only. M1d needs 3LO for the UI "Connect to Jira" flow. (a) Add 3LO upstream in `mulhamna/jira-commands` (you control it), (b) Suitest handles 3LO browser redirect + token storage, passes resulting bearer to `jirac-mcp` via env. Default: (b) for v1.0 ship velocity; (a) tracked as upstream issue.
12. **`jirac-mcp` exact tool names** — Suitest wrapper needs the exact MCP tool identifiers (`issue.create`? `create_issue`? `jira.issue.create`?). Need to capture `tools/list` output from a running `jirac-mcp` before PR-12 implementation. Blocks PR-12.
13. **`jirac-mcp` version pin for v1.0** — which release tag to bundle into Suitest image? Need a tagged release that includes the operations matrix listed in `MCP_PLUGINS.md §3`. If no tagged release yet, do we cut one or pin to a commit SHA?
14. **Linear/GitHub MCP adoption** — does `mulhamna` (or community) ship `linear-mcp` / `gh-mcp` we could adopt? If yes, PR-13/14 mirror the Jira pattern (thin Python adapter over MCP); if no, keep httpx for M1d and revisit in M2.
15. **Bundled vs optional toggle** — `jirac-mcp` always shipped in image (default-on Jira support) or pluggable provider user enables manually? Default: always-bundled per `MCP_PLUGINS.md §3` policy for built-in providers; `enabled=false` until integration is connected.

### Critical files for implementation

- `apps/api/src/suitest_api/routers/test_cases.py`
- `apps/api/src/suitest_api/services/defect_service.py`
- `apps/runner/src/suitest_runner/handlers/step_handler.py`
- `apps/web/src/components/cases/CaseEditor.tsx` (new — to be created)
- `packages/db/suitest_db/migrations/versions/` (new Alembic revisions for M1d-1)
