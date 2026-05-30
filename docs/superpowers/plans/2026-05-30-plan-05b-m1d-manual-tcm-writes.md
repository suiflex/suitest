# M1d — Manual TCM writes + Rule-based Defects + MCP-native Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining ZERO-tier acceptance criteria in M1 (#M1-12 → #M1-15, #M1-21 → #M1-27) so a self-host user on `SUITEST_LLM_PROVIDER=none` can fully author, edit, soft-delete, bulk-mutate, run, and triage test cases, with **rule-based** auto-defect filing and **MCP-native** external tracker / notification adapters. After M1d the ZERO deploy is the "TestRail + Playwright replacement" promised in `docs/PRODUCT.md` and `docs/ROADMAP.md` M1 DoD, and M2 (generators + MCP expansion) becomes unblockable.

**Capability Tier:** **ZERO only.** No LiteLLM, no LangGraph, no `require_tier(LOCAL|CLOUD)` introduced in M1d. Every endpoint is ZERO-compatible; AI surfaces stay hidden behind `<Gated feature="ai_generation">` per `CAPABILITY_TIERS.md`.

**Source Spec:** [`docs/superpowers/specs/2026-05-30-m1d-manual-tcm-writes.md`](../specs/2026-05-30-m1d-manual-tcm-writes.md) (amended 2026-05-30). Docker bundling de-risk: [`docs/superpowers/specs/2026-05-30-m1d-mcp-bundling-prototype.md`](../specs/2026-05-30-m1d-mcp-bundling-prototype.md) + `Dockerfile.mcp-prototype`.

**Estimated effort:** 33 tasks → 33 squash-merged PRs. Backend bulk is 18 PRs (M1d-1..M1d-19), FE 9 PRs (M1d-20..M1d-28), E2E/visual/release 5 PRs (M1d-29..M1d-33). Critical path ~10 working days assuming Wave 1 doc audit is already merged and prototype Dockerfile is reviewed. Parallel clusters (see § "Dependency graph") cut wall-clock to ~6 working days with 3 engineers.

**Dependencies:**
- **M1a** (read-only REST + workspace scoping + audit helper + pagination + error envelope) — already shipped (`apps/api`, `packages/db`).
- **M1b** (read-only UI + sidebar/topbar/Gated wrapper + WS subscribe primitive) — already shipped (`apps/web`).
- **M1c** (ARQ runner + `packages/mcp` client/pool/registry/routing + bundled `playwright-mcp`/`api-http-mcp`/`postgres-mcp` + WS `run.step.*` streaming + MinIO artifacts + workspace MCP session cap) — already shipped (tag `v0.4.0-m1c`, commits `828dace…e464c9d`).
- **Wave 1 doc audit (2026-05-30)** — `docs/DATA_MODEL.md`, `docs/API.md`, `docs/UI_SPEC.md`, `docs/CAPABILITY_TIERS.md`, `docs/ROADMAP.md`, `docs/AI_AGENT.md`, `docs/MCP_PLUGINS.md`, `docs/AUTONOMY.md` already aligned (e.g. canonical `DiagnosisKind`, `suites.deleted_at`, generate_public_id helper, `runs.tier_at_runtime` already present).
- **`packages/core/crypto`** (`aes_gcm_encrypt`/`decrypt`, master key from `SUITEST_ENCRYPTION_KEY`) — already shipped M0/M1a.
- **`packages/db/audit.py`** (`write_audit`) — already shipped M1a.
- **`packages/mcp/client` + `pool.acquire(provider, env_overrides=…)`** — shipped M1c. M1d reuses this for the Jira + GitHub MCP wrappers.
- **`packages/db/public_id.py::generate_public_id(prefix, workspace_id)`** wrapping Postgres function `generate_public_id(prefix TEXT, workspace_id TEXT)` (`docs/DATA_MODEL.md §8`) — already shipped.

---

## Prerequisites

Before starting M1d, verify all of the following at the start of every PR:

1. **`v0.4.0-m1c` tag exists in git** and `apps/runner` E2E green (`uv run pytest -m e2e -q apps/runner/tests`).
2. **`packages/mcp` exports** `client.open_session`, `pool.McpPool.acquire(..., env_overrides=...)`, `registry.McpRegistry.get`, `routing.resolve_provider`, `invoker.McpInvoker.invoke`, `errors.McpToolFailed/Timeout/ProviderUnavailable`.
3. **Bundled MCP providers seeded:** `playwright-mcp`, `api-http-mcp`, `postgres-mcp` rows present in `mcp_providers` with `enabled=true`. M1d-1 adds `jirac-mcp` + `github-mcp` rows with `enabled=false`.
4. **WS gateway** publishes to room `run:<runId>` and `workspace:<wsId>` (M1b/M1c verified).
5. **`packages/core/capabilities.resolve_tier()`** returns `Tier.ZERO` when `SUITEST_LLM_PROVIDER=none` and the FE `<Gated feature="ai_generation">` wrapper returns `<UpgradeHint>` in that tier.
6. **`Suitest.html`** still present at repo root (deletion deferred — see Open Question Q10).
7. **`Dockerfile.mcp-prototype`** at repo root has been reviewed; bundled binary URLs / image-size delta verdict captured (see `docs/superpowers/specs/2026-05-30-m1d-mcp-bundling-prototype.md`).

If any prerequisite is missing, **stop** and complete the missing milestone first — do not stub past it.

---

## Cross-cutting conventions

- **TDD always.** Each backend task: (1) write failing pytest, (2) implement, (3) green test, (4) refactor, (5) commit. Each FE task: (1) failing vitest, (2) implement, (3) green, (4) commit.
- **Conventional commits** per CLAUDE §6: `feat(api): ...`, `feat(web): ...`, `feat(db): ...`, `feat(mcp): ...`, `feat(runner): ...`, `feat(integrations): ...`, `chore(infra): ...`, `docs(m1d): ...`, `test(api): ...`. **No Co-Authored-By trailers** per user memory.
- **One acceptance criterion = one squash-merged PR** per CLAUDE §6 + `docs/ROADMAP.md` cross-cutting rule. Small PRs win.
- **mypy strict** (`disallow_untyped_defs=true`). No `Any` — use `TypedDict` / `Protocol` / generics. **No `as any` in TypeScript** — narrow with `unknown` + Zod validator.
- **No barrel files** (`__init__.py` stays empty except module docstring; `index.ts` re-exports forbidden).
- **Pydantic v2** with `ConfigDict(from_attributes=True, str_strip_whitespace=True)`. **SQLAlchemy 2 async** + Alembic for all DB access. **Repository pattern** — services never touch ORM directly.
- **Capability gate:** every endpoint declares `Depends(require_role(...))` per CLAUDE §3.1. **No `require_tier(...)` in M1d** — all routes are ZERO-compatible. Role names: `OWNER`, `ADMIN`, `QA`, `VIEWER` per `docs/DATA_MODEL.md §6`.
- **Audit log every mutation** via `packages/db/audit.py::write_audit(s, workspace_id, user_id, action, resource_type, resource_id, metadata)` — same transaction as the mutation.
- **OTel:** every external HTTP / MCP invocation wrapped in a span (`mcp.invoke`, `integration.http`, `webhook.recv`). Span attrs: `workspace_id`, `integration_kind`, `tool`, `outcome`.
- **WS channel naming:** `run:<runId>` per-run, `workspace:<wsId>` workspace-wide (see `docs/API.md §4`). New events from M1d: `case.created`, `case.updated`, `case.steps.replaced`, `defect.created`, `defect.updated`, `integration.error` — all on `workspace:<wsId>`.
- **AES-GCM** for stored secrets via `packages/core/crypto.aes_gcm_encrypt(plaintext, key)`. Master key from `SUITEST_ENCRYPTION_KEY` (32-byte base64). Never echo secret material in any `*Read` schema.
- **MCP invariant preserved:** every `Step` written via new endpoints carries `mcp_provider` + `target_kind`; validator rejects unregistered providers with `MCP_PROVIDER_NOT_REGISTERED` (404).
- **`If-Unmodified-Since` honored** by `PATCH /test-cases/:id` + `PATCH /test-cases/:id/steps` per `docs/API.md §47, §200, §205`; mismatched header → 409 `CONCURRENT_MODIFICATION` with `details.serverUpdatedAt`.
- **Cross-workspace requests return 404, not 403** (consistent with M1a invariant per `docs/API.md`).

---

## Canonical decisions encoded (do not re-debate during implementation)

The following decisions are **frozen** by Wave 1 doc audit + spec amendments. Plan tasks assume them as truth source — implementers must not re-litigate during PR review:

1. **`DiagnosisKind` enum** = `{REGRESSION, FLAKE, INFRA, SPEC_DRIFT, MANUAL_TRIAGE}` per `docs/DATA_MODEL.md §6` line ~1366. The pre-pivot `ENVIRONMENT / TEST_BUG` wording is stale.
2. **Public-id generation** = `generate_public_id(prefix, workspace_id)` helper from `docs/DATA_MODEL.md §8` (Postgres function + Python wrapper at `packages/db/public_id.py`). **No new global sequences** in M1d-1. Per-workspace `pubid_<wsid>_<prefix>` sequences are created lazily by the helper.
3. **Run dedup** = application-side Redis `SETNX dedup:run:{project_id}:{commit_sha}:{trigger}` with 60s TTL. **No `ix_runs_dedup_recent` partial unique index** — Postgres rejects `NOW()` in partial-index predicates (`docs/DATA_MODEL.md §3.6`).
4. **`JiraAdapter`** = thin wrapper over bundled `jirac-mcp@jira-mcp-v2.0.1` (Rust binary, direct GitHub Release download — `@mulham28/jirac-mcp` npm postinstall is broken). Cloud API token (Basic `email:token`) or DC PAT only. **No OAuth 3LO** (`jirac-mcp` binary doesn't support it). Tool execution delegated via `packages/mcp/client`; token injection per-invocation via `pool.acquire(provider, env_overrides={JIRA_URL, JIRA_EMAIL, JIRA_TOKEN, JIRA_AUTH_TYPE})`. Never write `~/.config/jira/config.toml`.
5. **`GitHubAdapter`** = thin wrapper over bundled `github-mcp-server@v1.1.2` (Go binary, fully static, from `github/github-mcp-server` GitHub Releases). GitHub App installation token mint + 50-min cache + AES-GCM storage stay Python-side. Tool execution delegated via `packages/mcp/client` with env `GITHUB_PERSONAL_ACCESS_TOKEN=<installation-token>` + `GITHUB_TOOLSETS=issues` (trim surface).
6. **`LinearAdapter`** = stays `httpx` GraphQL — no viable self-host Linear MCP (official is hosted-only, breaks ZERO air-gap). Reconsider in M2.
7. **`SlackAdapter`** = stays `httpx` incoming webhook — MCP wrapping a one-POST flow is overkill.
8. **Bundle both MCP binaries always-on** in the API + runner Docker images per `Dockerfile.mcp-prototype`. Image-size budget +45 MiB (~20 MiB Rust Jira + ~25 MiB Go GitHub) accepted (`docs/DEPLOYMENT.md §15`). Both seeded with `enabled=false`; flip to `true` on first successful integration connect.
9. **Workspace MCP session cap from M1c (`WorkspacePoolCap`)** is reused for webhook-triggered bulk runs and Jira/GitHub tool calls. No new concurrency primitives.
10. **`workspaces.strict_zero_validation` default = `TRUE`** for v1.0 unless override (safer; matches user expectation that ZERO ≠ undefined behaviour). Configurable per workspace via Settings → General.
11. **GitHub App env vars** = `SUITEST_GITHUB_APP_ID` (numeric, plaintext) + `SUITEST_GITHUB_APP_PRIVATE_KEY_PEM` (RSA PEM, secret — also AES-GCM at-rest if stored in `integrations.secrets_encrypted`; runtime decrypted before passing to `_mint_installation_token`). Documented in `docs/DEPLOYMENT.md §15`.
12. **Gating-suite fallback** = `200 {"ignored": true, "reason": "no_gating_suite"}` when project has neither `gating_suite_id` nor any `smoke`-tagged case. Webhook-receivers UX favors silent ignore over `400` to avoid noisy CI failures on un-onboarded projects.
13. **Bulk role gate** = `QA` (and ADMIN/OWNER), matching the case-CRUD role gate. Bulk soft-delete still produces one audit row per case so retention/restore semantics stay per-resource.
14. **Slack `test_connection` is intrusive** — posts an actual "Suitest connection test" message to the configured channel. FE confirms via dialog before invoking.
15. **`Suitest.html` lifespan** = kept through M2. Deleted after M2 generator UIs reach ≥95% visual match. M1d does not delete it.

---

## Open spec questions still requiring product confirmation

These are flagged in the spec § "Open questions" with proposed defaults. Implementers should adopt the proposed default and proceed; if product overrides any answer, that PR may need a small rework:

- **Q2 `workspaces.strict_zero_validation` default** — adopt `TRUE` (this plan). PR-1 ships migration accordingly.
- **Q3 GitHub App env var naming** — adopt `SUITEST_GITHUB_APP_ID` + `SUITEST_GITHUB_APP_PRIVATE_KEY_PEM` (this plan). PR-14 + `docs/DEPLOYMENT.md` aligned.
- **Q4 Gating-suite fallback semantics** — adopt `200 {ignored:true}` on no gating (this plan). PR-16 unit test pins behaviour.
- **Q6 Public-id sequence start** — **no longer relevant** — replaced by dynamic per-workspace sequences via `generate_public_id` helper. M1a seed already coexists with helper.
- **Q7 Bulk endpoint role gate** — adopt `QA+` for all bulk ops (this plan). PR-7 role test pins.
- **Q9 Slack `test_connection` intrusive** — adopt intrusive post (this plan). PR-15 ships; PR-25 FE wires confirm dialog.
- **Q10 `Suitest.html` lifespan** — adopt keep-through-M2 (this plan). PR-31 sets baseline but does not delete.

Any spec question not above is RESOLVED in the spec's "Open questions" section already.

---

## Migration summary table

Bird's-eye view of every Alembic revision M1d ships, what columns/indexes/seed rows each lands, and the rollback risk:

| Task | Alembic revision filename (suggested) | DDL summary | Rollback risk |
|------|--------------------------------------|--------------|----------------|
| M1d-1 | `2026XXXX_m1d_01_workspace_strict_zero_and_mcp_overrides.py` | `ALTER TABLE workspaces ADD COLUMN strict_zero_validation BOOLEAN NOT NULL DEFAULT 'true'`, `ALTER TABLE workspaces ADD COLUMN mcp_routing_overrides JSONB NOT NULL DEFAULT '{}'` | LOW — column with NOT NULL DEFAULT is a single ALTER; downgrade drops columns |
| M1d-1 | `2026XXXX_m1d_02_suite_mcp_overrides_and_soft_delete.py` | `ALTER TABLE suites ADD COLUMN mcp_routing_overrides JSONB NOT NULL DEFAULT '{}'`, `ALTER TABLE suites ADD COLUMN deleted_at TIMESTAMPTZ NULL`, `CREATE INDEX ix_suites_project_active ON suites(project_id) WHERE deleted_at IS NULL` | LOW — additive |
| M1d-1 | `2026XXXX_m1d_03_test_case_order_in_suite.py` | `ALTER TABLE test_cases ADD COLUMN order_in_suite INT NOT NULL DEFAULT 0`, `CREATE INDEX ix_test_cases_suite_order ON test_cases(suite_id, order_in_suite)` (composite); the single-column inline `index=True` on `order_in_suite` is autonamed by Alembic (`ix_test_cases_order_in_suite`) — do **not** duplicate as a third manual index | LOW — additive |
| M1d-1 | `2026XXXX_m1d_04_project_gating_suite.py` | `ALTER TABLE projects ADD COLUMN gating_suite_id VARCHAR(32) NULL REFERENCES suites(id) ON DELETE SET NULL` (matches actual `suites.id = String(32)` in `20260527_0004_projects_suites.py`) | LOW — nullable FK |
| M1d-1 | `2026XXXX_m1d_05_mcp_provider_pins.py` | `ALTER TABLE mcp_providers ADD COLUMN command_pin VARCHAR(200) NULL, ADD COLUMN image_pin VARCHAR(200) NULL, ADD COLUMN version_pin VARCHAR(100) NULL, ADD COLUMN git_ref VARCHAR(100) NULL` | LOW — additive |
| M1d-1 | `2026XXXX_m1d_06_defect_auto_dedup.py` | `CREATE UNIQUE INDEX uq_defects_auto_dedup ON defects(run_id, test_case_id) WHERE created_by = 'system'` | LOW — partial idx; downgrade drops |
| M1d-1 | `2026XXXX_m1d_07_mcp_provider_workspace_nullable_and_enabled.py` | `ALTER TABLE mcp_providers ALTER COLUMN workspace_id DROP NOT NULL`, `ALTER TABLE mcp_providers ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT 'true'` | LOW — additive col + relaxed FK |
| M1d-1 | `2026XXXX_m1d_08_seed_bundled_jirac_and_github_mcp.py` | `INSERT INTO mcp_providers (workspace_id=NULL, name, kind, transport, command_pin, enabled=false, …)` × 2 (jirac-mcp, github-mcp; both `enabled=false`) | LOW — data-only seed; downgrade `DELETE WHERE workspace_id IS NULL AND name IN ('jirac-mcp', 'github-mcp')` |
| M1d-10 | (shares M1d-1's `_06_defect_auto_dedup.py`) | n/a — index already lives in M1d-1 | n/a |
| Others | no new DDL | — | — |

All migrations are idempotent (`IF NOT EXISTS` on indexes; `ADD COLUMN IF NOT EXISTS` where the Alembic helper supports it). `downgrade()` round-trip is exercised by M1d-1 task tests.

---

## Task M1d-1 — Alembic migrations + bundled MCP seeds

**Goal:** Ship every schema change M1d needs in one well-scoped task, with a round-trip `upgrade→downgrade→upgrade` test, so subsequent tasks can assume the DDL is in place.

**Out of scope:** No new public-id sequences (use `generate_public_id` helper). No `ix_runs_dedup_recent` (Postgres rejects `NOW()` predicates). No hard-delete sweeper (deferred to M2+). No `audit_logs` schema changes (already final in M1a). No FE-visible behavior — this is pure DB plumbing.

**Tests to write** (in `apps/api/tests/db/test_m1d_migrations.py`, `pytest-asyncio` strict mode):

- `test_upgrade_all_m1d_revisions_round_trips` — `alembic upgrade head` then `alembic downgrade <last-pre-m1d-rev>` then `alembic upgrade head` against a clean testcontainers Postgres returns 0 from each.
- `test_workspaces_strict_zero_validation_defaults_true` — INSERT a workspace without specifying the column; assert `SELECT strict_zero_validation FROM workspaces WHERE id=…` returns `TRUE`.
- `test_workspaces_mcp_routing_overrides_defaults_empty_object` — INSERT without column; assert `'{}'::jsonb` round-trips.
- `test_suites_deleted_at_partial_index_excludes_deleted` — INSERT two suites in one project, one with `deleted_at=NOW()`; `EXPLAIN SELECT * FROM suites WHERE project_id=… AND deleted_at IS NULL` shows the partial index is chosen.
- `test_test_cases_order_in_suite_defaults_zero` — INSERT without column; assert `0`.
- `test_projects_gating_suite_id_nullable_fk_on_delete_set_null` — create suite, set as gating; delete suite; assert `projects.gating_suite_id IS NULL`.
- `test_mcp_provider_pins_all_nullable` — INSERT row with all four pin columns NULL; assert no constraint violation.
- `test_defects_auto_dedup_partial_unique_scoped_to_system` — INSERT defect (`run_id=r1, case_id=c1, created_by='system'`); INSERT second with same `(r1, c1, 'system')` → `IntegrityError`. INSERT third with `(r1, c1, 'user_u1')` → succeeds (partial idx doesn't apply).
- `test_mcp_providers_workspace_id_nullable_post_m1d` — INSERT a row with `workspace_id=NULL`; assert no NOT NULL constraint violation.
- `test_mcp_providers_enabled_defaults_true_post_m1d` — INSERT a row without specifying `enabled`; assert `SELECT enabled` returns `TRUE`.
- `test_seeded_jirac_mcp_row_disabled` — `SELECT enabled, command_pin, workspace_id FROM mcp_providers WHERE name='jirac-mcp'` → `(False, 'jirac-mcp@jira-mcp-v2.0.1', None)`.
- `test_seeded_github_mcp_row_disabled` — `SELECT enabled, command_pin, workspace_id FROM mcp_providers WHERE name='github-mcp'` → `(False, 'github-mcp-server@v1.1.2', None)`.
- `test_bundled_mcp_providers_post_upgrade_query` — verification query `SELECT name, enabled, workspace_id FROM mcp_providers WHERE workspace_id IS NULL ORDER BY name` returns exactly 2 rows: `('github-mcp', False, None)` and `('jirac-mcp', False, None)`.
- `test_no_new_global_public_id_sequences` — `SELECT relname FROM pg_class WHERE relkind='S' AND relname LIKE 'pubid_%global%'` returns 0 rows (helper-managed dynamic sequences only).
- `test_no_ix_runs_dedup_recent_index` — `SELECT indexname FROM pg_indexes WHERE indexname='ix_runs_dedup_recent'` returns 0 rows.

**Implementation:**

- Create 8 Alembic revisions under `packages/db/alembic/versions/` per the Migration summary table above. Each revision: `revision = "…"`, `down_revision = "<previous>"`, `branch_labels = None`, `depends_on = None`, plus `upgrade()` + `downgrade()` that are exact inverses.
- The **first** M1d revision pins `down_revision = "0015_run_step_logs"` (the head of M1c, file `20260529_0015_run_step_logs.py`). Subsequent revisions chain to the previous M1d rev.
- Revision filenames are `YYYYMMDDHHMM_m1d_<NN>_<short_desc>.py` style; use `alembic revision -m "m1d 01 workspace strict zero"` to generate the boilerplate, then hand-edit.
- For `projects.gating_suite_id` use `sa.String(length=32)` (NOT `UUID`) to match the actual `suites.id` width declared in `20260527_0004_projects_suites.py:51`. Add the FK with `ondelete="SET NULL"` so deleting a gating suite nulls the project pointer rather than cascading:
  ```
  op.add_column("projects", sa.Column("gating_suite_id", sa.String(length=32), nullable=True))
  op.create_foreign_key("fk_projects_gating_suite_id", "projects", "suites",
                        ["gating_suite_id"], ["id"], ondelete="SET NULL")
  ```
- For `mcp_providers` pin columns use exact `sa.String(length=N)` (NOT `Text`):
  ```
  op.add_column("mcp_providers", sa.Column("command_pin", sa.String(length=200), nullable=True))
  op.add_column("mcp_providers", sa.Column("image_pin",   sa.String(length=200), nullable=True))
  op.add_column("mcp_providers", sa.Column("version_pin", sa.String(length=100), nullable=True))
  op.add_column("mcp_providers", sa.Column("git_ref",     sa.String(length=100), nullable=True))
  ```
- For `mcp_providers.workspace_id` nullable + `enabled` add (in revision `_07`):
  ```
  op.alter_column("mcp_providers", "workspace_id", existing_type=sa.String(length=32),
                  nullable=True)
  op.add_column("mcp_providers", sa.Column(
      "enabled", sa.Boolean(), nullable=False, server_default=sa.text("'true'"),
  ))
  ```
  Inverse `downgrade()`:
  ```
  op.drop_column("mcp_providers", "enabled")
  op.alter_column("mcp_providers", "workspace_id", existing_type=sa.String(length=32),
                  nullable=False)
  ```
  Note: downgrade of `workspace_id nullable=True → nullable=False` will fail if bundled rows (workspace_id IS NULL) exist; the downgrade must first DELETE bundled rows (handled by the seed revision's own downgrade running first via the linear chain).
- For Boolean `server_default`, use the lowercase SQL literal `sa.text("'true'")` — Alembic / SQLAlchemy normalises to a string, not the Python keyword `True`. Same for `strict_zero_validation`.
- For `suites.deleted_at` + partial idx, use:
  ```
  op.add_column("suites", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
  op.create_index("ix_suites_project_active", "suites", ["project_id"],
                  postgresql_where=sa.text("deleted_at IS NULL"))
  ```
- For `uq_defects_auto_dedup`:
  ```
  op.create_index("uq_defects_auto_dedup", "defects", ["run_id", "test_case_id"],
                  unique=True, postgresql_where=sa.text("created_by = 'system'"))
  ```
- For seed rows, use `op.bulk_insert(mcp_providers_table, [...])` with `workspace_id=None` (Python) / `NULL` (SQL) — `mcp_providers.workspace_id` is now nullable for bundled/global providers, so **no `_builtin_` sentinel workspace is needed**. Both bundled rows ship with `enabled=False`, `kind="issue-tracker"`, `transport="stdio"`, and the spec'd `command_pin`. Downgrade: `DELETE FROM mcp_providers WHERE workspace_id IS NULL AND name IN ('jirac-mcp', 'github-mcp')`.
- ORM updates in `packages/db/suitest_db/models/workspace.py`, `project.py`, `suite.py`, `test_case.py`, `mcp_provider.py`, `defect.py` to add the new mapped columns. Use `Mapped[bool]`, `Mapped[dict[str, Any]]` (JSONB), `Mapped[datetime | None]`, `Mapped[int]`, `Mapped[uuid.UUID | None]`, `Mapped[str | None]` respectively.
- Bump `packages/db/pyproject.toml` version to `0.5.0` to signal schema bump.

**Verification:**

- `uv run alembic upgrade head` against a clean Postgres returns clean.
- `uv run alembic downgrade -8` returns clean (rolls back all 8 M1d revisions).
- `uv run alembic upgrade head` again returns clean.
- After `upgrade head`, run:
  ```sql
  SELECT name, enabled, workspace_id
  FROM mcp_providers
  WHERE workspace_id IS NULL
  ORDER BY name;
  ```
  Expected: exactly 2 rows — `('github-mcp', false, NULL)` and `('jirac-mcp', false, NULL)`.
- `uv run pytest apps/api/tests/db/test_m1d_migrations.py -q` → all green.
- `uv run mypy packages/db` → 0 errors.

**Done when:**

- [ ] 8 Alembic revisions added under `packages/db/alembic/versions/` (first chains to `down_revision = "0015_run_step_logs"`).
- [ ] All ORM models updated with new typed columns (incl. `McpProvider.workspace_id: Mapped[str | None]` and `McpProvider.enabled: Mapped[bool]`).
- [ ] Round-trip migration test green.
- [ ] Seeded `jirac-mcp` + `github-mcp` rows present after `upgrade head` with `workspace_id IS NULL` and `enabled=false` (verified by test + the SQL query above).
- [ ] `mypy --strict packages/db` clean.
- [ ] Commit message: `feat(db): m1d migrations — strict_zero, mcp_overrides, soft-delete, defect-dedup, mcp workspace nullable + enabled, bundled MCP seeds`.

**Cross-refs:** `docs/DATA_MODEL.md §3.2` (Workspace), `§3.3` (Project, Suite + deleted_at), `§3.4` (TestCase + order_in_suite), `§4.3` (McpProvider — workspace_id nullable + enabled), `§5` (Modified tables delta), `§6` (enums), `§8` (`generate_public_id` helper), `docs/MCP_PLUGINS.md §3` (bundled providers list).

---

## Task M1d-1.5 — Repository pattern extensions (pre-flight for write tasks)

> **Note:** Not a numbered acceptance criterion, but a recommended sub-task for the engineer landing PR-1 → PR-2 to avoid five repo-pattern PRs each fighting the same boilerplate. Land alongside PR-1 or as a sibling commit at start of PR-2.

**Goal:** Extend the M1a repositories (`TestCaseRepository`, `SuiteRepository`, `ProjectRepository`, `RequirementRepository`, `DefectRepository`, `IntegrationRepository`, `WorkspaceRepository`) with the write methods M1d needs, so each downstream task can focus on routing + services + tests.

**Out of scope:** Service-layer logic (that lives in `*_service.py`). API routes (those are per-task).

**Tests to write** (in `apps/api/tests/repositories/test_repositories_writes.py`):

- `test_test_case_repo_create_returns_row_with_assigned_TC_public_id`
- `test_test_case_repo_mark_deleted_idempotent`
- `test_test_case_repo_clear_deleted_idempotent`
- `test_test_case_repo_list_for_update_locks_row_for_concurrent_append`
- `test_suite_repo_list_active_uses_partial_idx_ix_suites_project_active`
- `test_suite_repo_reorder_cases_atomic_via_unnest`
- `test_project_repo_create_with_slug_collision_retries_with_suffix`
- `test_requirement_repo_create_with_REQ_public_id`
- `test_defect_repo_create_with_SUIT_public_id_and_partial_idx_dedup`
- `test_integration_repo_first_create_for_kind_flips_bundled_mcp_enabled_true`
- `test_workspace_repo_update_strict_zero_validation`

**Implementation:**

Add the following methods (each typed signature only — bodies are straightforward SQLAlchemy 2 async with `select`/`update`/`insert`):

- `TestCaseRepository`:
  ```
  async def create(self, *, workspace_id: str, suite_id: str, body: TestCaseCreate, public_id: str) -> TestCase: ...
  async def update_metadata(self, case_id: str, body: TestCaseUpdate, *, if_unmodified_since: datetime | None) -> TestCase: ...
  async def replace_steps(self, case_id: str, steps: list[TestStepCreate]) -> TestCase: ...
  async def append_step(self, case_id: str, step: TestStepCreate) -> TestStep: ...
  async def reorder_steps(self, case_id: str, ordered_ids: list[str]) -> list[TestStep]: ...
  async def duplicate(self, case_id: str, *, new_public_id: str) -> TestCase: ...
  async def mark_deleted(self, case_id: str, *, deleted_at: datetime) -> None: ...
  async def clear_deleted(self, case_id: str) -> None: ...
  async def list_ids_by_tag(self, project_id: str, tag: str) -> list[str]: ...
  async def get_for_update(self, case_id: str) -> TestCase | None: ...  # SELECT … FOR UPDATE
  async def bulk_apply(self, ids: list[str], action: BulkAction, payload: BulkPayload) -> int: ...
  ```
- `SuiteRepository`:
  ```
  async def create(self, *, project_id: str, body: SuiteCreate) -> Suite: ...
  async def update_metadata(self, suite_id: str, body: SuiteUpdate) -> Suite: ...
  async def reorder_cases(self, suite_id: str, ordered_case_ids: list[str]) -> None: ...
  async def soft_delete_with_cascade(self, suite_id: str, *, deleted_at: datetime) -> int: ...
  async def restore(self, suite_id: str) -> None: ...
  async def count_active_children(self, suite_id: str) -> int: ...
  async def list_active(self, project_id: str) -> list[Suite]: ...  # uses partial idx
  ```
- `ProjectRepository`:
  ```
  async def create(self, *, workspace_id: str, body: ProjectCreate, slug: str) -> Project: ...
  async def update(self, project_id: str, body: ProjectUpdate) -> Project: ...
  async def set_gating_suite(self, project_id: str, suite_id: str | None) -> None: ...
  async def soft_delete_with_cascade(self, project_id: str, *, deleted_at: datetime) -> int: ...
  ```
- `RequirementRepository`:
  ```
  async def create(self, *, project_id: str, workspace_id: str, body: RequirementCreate, public_id: str) -> Requirement: ...
  async def update(self, req_id: str, body: RequirementUpdate) -> Requirement: ...
  async def soft_delete(self, req_id: str) -> None: ...
  ```
- `RequirementLinkRepository`:
  ```
  async def create(self, *, requirement_id: str, case_id: str) -> RequirementLink: ...
  async def delete(self, *, requirement_id: str, case_id: str) -> int: ...
  ```
- `DefectRepository`:
  ```
  async def create(self, *, workspace_id: str, body: DefectCreate, public_id: str, created_by: str,
                    agent_diagnosis_kind: DiagnosisKind | None) -> Defect: ...
  async def update(self, defect_id: str, body: DefectUpdate) -> Defect: ...
  async def file_auto(self, *, workspace_id: str, run_id: str, test_case_id: str,
                       categorized: CategorizedDefect, public_id: str) -> Defect | None: ...
  # ↑ Catches IntegrityError on uq_defects_auto_dedup → returns None.
  ```
- `IntegrationRepository`:
  ```
  async def create(self, *, workspace_id: str, kind: str, config_json: dict, secrets_encrypted: bytes) -> Integration: ...
  async def update(self, integration_id: str, *, config_json: dict | None, secrets_encrypted: bytes | None) -> Integration: ...
  async def soft_delete(self, integration_id: str) -> None: ...
  async def get_default_for(self, workspace_id: str, kind: str, *, role: str) -> Integration | None: ...
  # role = "defects" | "notifications"
  ```
- `McpProviderRepository.flip_enabled(provider_name: str, enabled: bool) -> None` — used on first Jira/GitHub connect.
- `WorkspaceRepository.update_settings(workspace_id, *, strict_zero_validation, mcp_routing_overrides) -> Workspace`.

**Verification:**

- `pytest apps/api/tests/repositories -q` → green.
- `mypy --strict packages/db apps/api` clean.

**Done when:**

- [ ] All repo methods landed with mypy-strict signatures.
- [ ] Tests cover each method's happy path + at least one edge case (dedup, idempotency, FOR UPDATE).
- [ ] Commit: `feat(db): repository extensions for m1d writes — soft-delete, reorder, bulk, auto-file dedup, integration secrets`.

**Cross-refs:** `docs/DATA_MODEL.md §3.x` (per-table ORM), `packages/db/suitest_db/repositories/`.

---

## Task M1d-2 — Test case writes (POST/PATCH/duplicate + step replace/append)

**Goal:** Ship the four write endpoints that unblock manual TCM: `POST /test-cases` (create), `PATCH /test-cases/:id` (metadata + tag replace), `PATCH /test-cases/:id/steps` (atomic replace), `POST /test-cases/:id/steps` (append), `POST /test-cases/:id/duplicate`. All routes honor `STEPS_REQUIRE_CODE_IN_ZERO_LLM` and `MCP_PROVIDER_NOT_REGISTERED`; `PATCH` honors `If-Unmodified-Since` → 409 `CONCURRENT_MODIFICATION`.

**Out of scope:** Soft-delete (M1d-3), bulk update (M1d-7), ad-hoc run shortcut (M1d-8), step reorder via `PATCH /test-cases/:id/steps/reorder` (covered atomically inside step replace; standalone reorder endpoint is M1d-21 FE territory — backend ships in this task as `PATCH /test-cases/:id/steps/reorder` per `docs/API.md §206`).

**Tests to write** (in `apps/api/tests/routers/test_test_cases_writes.py`):

- `test_post_test_cases_creates_with_steps_and_returns_public_id_TC_format`
- `test_post_test_cases_zero_tier_rejects_step_without_code_400_STEPS_REQUIRE_CODE_IN_ZERO_LLM_with_stepIndex`
- `test_post_test_cases_unregistered_mcp_provider_returns_404_MCP_PROVIDER_NOT_REGISTERED`
- `test_post_test_cases_unknown_target_kind_returns_400`
- `test_post_test_cases_cross_workspace_suite_id_returns_404_not_403` (workspace-scoping invariant)
- `test_patch_test_cases_with_If_Unmodified_Since_older_than_server_returns_409_CONCURRENT_MODIFICATION_with_serverUpdatedAt`
- `test_patch_test_cases_without_If_Unmodified_Since_uses_last_write_wins`
- `test_patch_test_cases_metadata_only_does_not_touch_steps`
- `test_patch_test_cases_steps_atomic_replace_increments_updated_at_and_emits_case_steps_replaced_WS`
- `test_patch_test_cases_steps_validates_each_step_code_for_zero_tier`
- `test_post_test_cases_steps_append_uses_SELECT_MAX_FOR_UPDATE_under_concurrency` (use `asyncio.gather` two appends; assert order monotonic)
- `test_post_test_cases_duplicate_clones_metadata_and_steps_and_assigns_new_TC_id`
- `test_post_test_cases_duplicate_does_not_clone_runs_or_defects`
- `test_post_test_cases_role_VIEWER_returns_403` (positive QA+/ADMIN+/OWNER each pass)
- `test_patch_test_cases_steps_reorder_atomic_rejects_missing_or_duplicate_ids_400`

**Implementation:**

- **Pydantic schemas** (`packages/shared/suitest_shared/schemas/test_case.py`): `TestCaseCreate`, `TestCaseUpdate`, `TestCaseRead`, `TestStepCreate`, `TestStepUpdate`, `TestStepRead`, `StepReorderRequest`. Use `ConfigDict(from_attributes=True, str_strip_whitespace=True, extra="forbid")`. `TestStepCreate.mcp_provider: Annotated[str, Field(min_length=1)]`, `target_kind: TargetKind`, `code: str | None = None`, `action: str`, `expected: str = ""`, `order: int = Field(ge=0)`.
- **Validator** at `apps/api/src/suitest_api/services/test_case_validator.py`:
  ```
  def validate_steps(steps: Sequence[TestStepCreate],
                     tier: Tier,
                     workspace_settings: WorkspaceSettings,
                     registered_mcp_names: set[str]) -> None
  ```
  Raises `StepsRequireCodeError(step_index=N)` or `McpProviderNotRegisteredError(name=…)`.
- **Router** at `apps/api/src/suitest_api/routers/test_cases.py` (extend existing M1a router):
  ```
  @router.post("", response_model=TestCaseRead, status_code=201,
               dependencies=[Depends(require_role({Role.QA, Role.ADMIN, Role.OWNER}))])
  async def create_test_case(body: TestCaseCreate, …) -> TestCaseRead: …

  @router.patch("/{case_id}", response_model=TestCaseRead,
                dependencies=[Depends(require_role({Role.QA, Role.ADMIN, Role.OWNER}))])
  async def update_test_case(case_id: str, body: TestCaseUpdate,
                              if_unmodified_since: Annotated[datetime | None, Header(alias="If-Unmodified-Since")] = None,
                              …) -> TestCaseRead: …
  ```
- **Service** at `apps/api/src/suitest_api/services/test_case_service.py`: `create(workspace_id, user_id, body)`, `update(case_id, body, if_unmodified_since)`, `replace_steps(case_id, steps, if_unmodified_since)`, `append_step(case_id, step)`, `duplicate(case_id, user_id)`. Each method opens a single transaction, runs validator (using the registered MCP set from `McpProviderRepository.list_names_for_workspace`), calls repo, writes audit, emits WS event via injected `WsPublisher`.
- **WS events** published to room `workspace:<wsId>`: `case.created` (`{caseId, publicId, suiteId, by}`), `case.updated` (`{caseId, fields:[…]}`), `case.steps.replaced` (`{caseId, stepCount}`). Use existing M1b `WsPublisher`.
- **Concurrency:** append uses `SELECT MAX(order_in_suite) FROM test_steps WHERE test_case_id=:cid FOR UPDATE` inside the same transaction.
- **Error envelope** matches `docs/API.md §56,58,62` — `{"error":{"code":"STEPS_REQUIRE_CODE_IN_ZERO_LLM","message":…,"details":{"stepIndex":N,"caseId":…}}}`.

**Verification:**

- `pytest apps/api/tests/routers/test_test_cases_writes.py -q` → all green.
- Smoke `curl -X POST … /api/v1/test-cases` from a seeded workspace creates a case with `publicId="TC-…"`.
- WS subscriber on `workspace:<wsId>` receives `case.created` event within 100ms.
- `mypy --strict apps/api packages/shared` clean.

**Done when:**

- [ ] `POST /test-cases` + `PATCH /test-cases/:id` + `PATCH /test-cases/:id/steps` + `POST /test-cases/:id/steps` + `PATCH /test-cases/:id/steps/reorder` + `POST /test-cases/:id/duplicate` shipped.
- [ ] Validator covers ZERO `STEPS_REQUIRE_CODE_IN_ZERO_LLM` + `MCP_PROVIDER_NOT_REGISTERED` with the exact JSON shape per `docs/API.md §3`.
- [ ] `If-Unmodified-Since` 409 round-trips with `details.serverUpdatedAt`.
- [ ] Cross-workspace IDs return 404.
- [ ] Audit row per write; WS event per write.
- [ ] Commit: `feat(api): test case writes — create/update/replace-steps/append/duplicate with zero-tier validator`.

**Cross-refs:** `docs/API.md §3.1 (test-cases)` lines 197-309, `docs/DATA_MODEL.md §3.4` (TestCase + TestStep ORM), `§6` (enums), `docs/UI_SPEC.md §4` (case editor — drives FE M1d-21).

---

## Task M1d-3 — Soft delete + restore (test cases)

**Goal:** Ship `DELETE /test-cases/:id` (soft) + `POST /test-cases/:id/restore` (idempotent). List endpoints exclude `deleted_at IS NOT NULL` by default; `?includeDeleted=true` admin-only query param surfaces tombstoned rows.

**Out of scope:** Suite cascade soft-delete (M1d-4). Project soft-delete (M1d-5). Hard-delete sweeper background job (deferred to M2+). FE `undoToast` (M1d-23). Hard-delete via DELETE `?force=true` (not in scope; M2+).

**Tests to write** (in `apps/api/tests/routers/test_test_cases_soft_delete.py`):

- `test_delete_returns_204_and_sets_deleted_at` — assert column populated with `NOW()`-ish timestamp.
- `test_delete_is_idempotent_re_delete_returns_404` (per `docs/API.md` — first delete soft-deletes; second sees row already gone from non-`includeDeleted` queries → 404).
- `test_delete_unknown_id_returns_404_not_403`
- `test_restore_returns_204_and_clears_deleted_at`
- `test_restore_already_active_returns_204_idempotent`
- `test_restore_never_existed_returns_404`
- `test_list_excludes_deleted_by_default`
- `test_list_includeDeleted_true_admin_only_includes_tombstones` — VIEWER `?includeDeleted=true` returns 403 (per `docs/API.md`).
- `test_delete_emits_case_deleted_WS_event`
- `test_restore_emits_case_restored_WS_event`
- `test_delete_audit_row_action_test_case_soft_deleted`
- `test_restore_audit_row_action_test_case_restored`
- `test_delete_role_VIEWER_403`

**Implementation:**

- Router additions:
  ```
  @router.delete("/{case_id}", status_code=204,
                 dependencies=[Depends(require_role({Role.QA, Role.ADMIN, Role.OWNER}))])
  async def delete_test_case(case_id: str, …) -> None: …

  @router.post("/{case_id}/restore", status_code=204,
               dependencies=[Depends(require_role({Role.QA, Role.ADMIN, Role.OWNER}))])
  async def restore_test_case(case_id: str, …) -> None: …
  ```
- Repo method `mark_deleted(case_id, deleted_at=utcnow())` + `clear_deleted(case_id)`.
- Service applies idempotency: `delete` no-ops if already deleted (returns 204 only when the row exists at all; 404 if `SELECT … WHERE id=:cid` returns 0).
- `TestCaseRepository.list(...)` accepts `include_deleted: bool = False`; the default LIST query adds `WHERE deleted_at IS NULL`.
- Audit metadata: `{"deleted_at": "…"}` on delete; `{"restored_at": "…"}` on restore.
- WS events: `case.deleted` (`{caseId, publicId}`), `case.restored` (`{caseId, publicId}`) on `workspace:<wsId>`.

**Verification:**

- `pytest apps/api/tests/routers/test_test_cases_soft_delete.py -q` → green.
- `curl -X DELETE … /api/v1/test-cases/<TC-1045>` → `204`; subsequent `GET` returns `404`; subsequent `POST … /restore` returns `204` and the case re-appears in `GET /test-cases`.
- `mypy --strict apps/api packages/db` clean.

**Done when:**

- [ ] `DELETE` + `POST /restore` shipped; both idempotent.
- [ ] List endpoints exclude tombstones by default.
- [ ] `?includeDeleted=true` ADMIN/OWNER gated.
- [ ] WS + audit per mutation.
- [ ] Commit: `feat(api): test case soft-delete + restore with idempotent semantics + audit`.

**Cross-refs:** `docs/API.md §3.1` lines 201-211, `docs/DATA_MODEL.md §3.4` (`test_cases.deleted_at` + `ix_test_cases_deleted_at`).

---

## Task M1d-4 — Suite CRUD with case_order reorder + cascade soft-delete

**Goal:** Ship `POST /suites`, `PATCH /suites/:id` (metadata + `case_order`), `DELETE /suites/:id?confirmCascade=true`, `POST /suites/:id/restore`. Reorder updates `test_cases.order_in_suite` atomically. Cascade soft-deletes child cases as well (per `confirmCascade=true` body flag).

**Out of scope:** Suite-level MCP routing overrides UI (column lands here but FE editor lives in M1d-28 workspace settings). Suite test cases bulk reassign across suites (covered in M1d-7 bulk). Auto-restore child cases on `/restore` — explicitly out per `docs/API.md §328`.

**Tests to write** (in `apps/api/tests/routers/test_suites_crud.py`):

- `test_post_suite_creates_under_project_with_SUITE_public_id` (note: confirm — per `docs/DATA_MODEL.md`, suites use a public id pattern; if not pre-existing, fall back to UUID + name slug — see Cross-refs).
- `test_post_suite_cross_workspace_project_id_returns_404`
- `test_patch_suite_metadata_updates_name_description`
- `test_patch_suite_case_order_reorder_atomic_updates_test_cases_order_in_suite_in_single_transaction`
- `test_patch_suite_case_order_with_unknown_case_id_returns_400_with_details_unknown`
- `test_patch_suite_case_order_missing_case_id_returns_400_with_details_missing`
- `test_delete_suite_without_confirmCascade_returns_409_CONFIRM_CASCADE_REQUIRED_with_child_count`
- `test_delete_suite_with_confirmCascade_true_soft_deletes_suite_and_child_cases`
- `test_delete_suite_idempotent_re_delete_returns_404`
- `test_restore_suite_returns_204_and_clears_deleted_at_but_does_NOT_restore_children`
- `test_list_suites_excludes_deleted_by_default_uses_partial_index_ix_suites_project_active`
- `test_suite_writes_role_QA_or_higher_VIEWER_403`

**Implementation:**

- Pydantic schemas in `packages/shared/suitest_shared/schemas/suite.py`: `SuiteCreate`, `SuiteUpdate` (incl. optional `case_order: list[str] | None`), `SuiteRead`, `SuiteDeleteRequest` (with `confirmCascade: bool = False`).
- Router under `apps/api/src/suitest_api/routers/suites.py` (extends M1a read router). Same dep-injection patterns as M1d-2.
- Service at `apps/api/src/suitest_api/services/suite_service.py`:
  - `reorder_cases(suite_id, ordered_case_ids)` validates that the set of `ordered_case_ids` matches exactly the active (non-deleted) cases in the suite; uses `UPDATE test_cases SET order_in_suite=$rank FROM unnest($ids, $ranks)` (CTE or `WITH ord AS …`).
  - `soft_delete_with_cascade(suite_id, confirm_cascade)` raises `ConfirmCascadeRequiredError(child_count)` if `confirm_cascade=False`. With it true, single transaction: `UPDATE suites SET deleted_at=NOW() WHERE id=:sid AND deleted_at IS NULL` + `UPDATE test_cases SET deleted_at=NOW() WHERE suite_id=:sid AND deleted_at IS NULL`.
- Audit rows: `suite.created`, `suite.updated`, `suite.case_order.reordered`, `suite.soft_deleted_with_cascade` (metadata: `{child_case_ids: […]}`), `suite.restored`.

**Verification:**

- `pytest apps/api/tests/routers/test_suites_crud.py -q` → green.
- `EXPLAIN SELECT * FROM suites WHERE project_id=… AND deleted_at IS NULL` picks `ix_suites_project_active` (verified inside one test).
- `mypy --strict apps/api packages/db packages/shared` clean.

**Done when:**

- [ ] Suite CRUD shipped, role-gated, cross-workspace 404.
- [ ] `case_order` reorder atomic with `UPDATE …FROM unnest(...)` pattern.
- [ ] Cascade soft-delete requires `confirmCascade=true`; otherwise 409.
- [ ] Restore does not cascade-restore children (per `docs/API.md §328`).
- [ ] WS + audit per mutation.
- [ ] Commit: `feat(api): suite CRUD with case_order reorder + cascade soft-delete`.

**Cross-refs:** `docs/API.md §3.2 (suites)` lines 313-329, `docs/DATA_MODEL.md §3.3` (Suite ORM + `deleted_at` + partial idx + `mcp_routing_overrides`).

---

## Task M1d-5 — Project CRUD (ADMIN/OWNER-gated, slug autogen, cascade-confirm)

**Goal:** Ship `POST /projects`, `PATCH /projects/:id`, `DELETE /projects/:id?confirmCascade=true`. ADMIN/OWNER only. Slug derived from name via `slugify()` if not provided; cascade soft-deletes all child suites + test cases + requirements with `confirmCascade=true`.

**Out of scope:** Project membership management (deferred to M1d-28 workspace settings). Project per-feature flag toggles. Project-level webhook config — handled per-integration in M1d-19. Hard-delete projects.

**Tests to write** (in `apps/api/tests/routers/test_projects_crud.py`):

- `test_post_project_slug_autogenerated_from_name_lowercase_hyphenated`
- `test_post_project_explicit_slug_overrides_autogen`
- `test_post_project_duplicate_slug_in_workspace_returns_409_DUPLICATE_PROJECT_SLUG`
- `test_post_project_role_QA_returns_403` (only ADMIN/OWNER allowed)
- `test_patch_project_name_regenerates_slug_only_if_slug_unchanged`
- `test_patch_project_gating_suite_id_validates_suite_lives_in_same_project_400_CROSS_PROJECT_GATING_SUITE`
- `test_delete_project_without_confirmCascade_returns_409_with_child_counts`
- `test_delete_project_with_confirmCascade_true_soft_deletes_project_suites_cases_requirements_in_single_transaction`
- `test_delete_project_role_QA_returns_403`
- `test_cross_workspace_project_id_returns_404`

**Implementation:**

- Pydantic: `ProjectCreate(name, slug=None, description="")`, `ProjectUpdate(name?, slug?, description?, gating_suite_id?)`, `ProjectRead`, `ProjectDeleteRequest(confirmCascade=False)`.
- Slug helper at `apps/api/src/suitest_api/utils/slug.py`: `slugify(name: str) -> str` (lowercase, hyphenate non-alphanumeric, collapse runs, strip ends). Avoid `python-slugify` dep — inline 10-line function (CLAUDE §2.2 no-new-deps).
- Service `project_service.py`:
  - `create(workspace_id, body)` — generate slug, retry once with `-2` suffix on collision (then bubble 409).
  - `update(project_id, body)` — if `gating_suite_id` set, verify suite's `project_id == project_id` (else `CROSS_PROJECT_GATING_SUITE`).
  - `soft_delete_with_cascade(project_id, confirm_cascade)` — single transaction with four `UPDATE … SET deleted_at=NOW()` for project, suites, test_cases, requirements (via project_id FK chain).
- Role gate: `Depends(require_role({Role.ADMIN, Role.OWNER}))` on all four endpoints.
- Audit rows: `project.created`, `project.updated`, `project.gating_suite_changed`, `project.soft_deleted_with_cascade`.

**Verification:**

- `pytest apps/api/tests/routers/test_projects_crud.py -q` → green.
- Slug collision retry test exercises the `-2` suffix path.
- `mypy --strict apps/api packages/shared` clean.

**Done when:**

- [ ] Project CRUD shipped, ADMIN/OWNER gated.
- [ ] Slug autogen + collision retry.
- [ ] `gating_suite_id` validated to be in-project.
- [ ] Cascade soft-delete confirmation flow.
- [ ] Commit: `feat(api): project CRUD with slug autogen + cascade soft-delete + gating_suite validation`.

**Cross-refs:** `docs/API.md §3.x (projects)`, `docs/DATA_MODEL.md §3.3` (Project ORM + `gating_suite_id`).

---

## Task M1d-6 — Requirement + Link CRUD

**Goal:** Ship `POST/PATCH/DELETE /requirements/:id` (REQ-N public id via helper, ADMIN/OWNER for create/delete, QA+ for update) and `POST/DELETE /requirements/:id/links/:case_id` link CRUD with `CROSS_WORKSPACE_LINK` 400 enforcement.

**Out of scope:** Requirement traceability matrix view (already shipped in M1a/M1b read-only). Bulk link operations. Requirement import from external tools (deferred to M2).

**Tests to write** (in `apps/api/tests/routers/test_requirements_links.py`):

- `test_post_requirement_uses_REQ_public_id_from_helper` — assert `publicId.startswith("REQ-")` and `int(suffix) >= 1`.
- `test_post_requirement_cross_workspace_project_id_returns_404`
- `test_patch_requirement_updates_title_description_priority`
- `test_delete_requirement_soft_deletes_and_clears_links`
- `test_post_link_creates_join_row_between_requirement_and_case`
- `test_post_link_cross_workspace_case_id_returns_400_CROSS_WORKSPACE_LINK_with_workspace_ids_in_details`
- `test_post_link_duplicate_returns_204_idempotent` (POST same link twice → second is no-op)
- `test_delete_link_returns_204`
- `test_delete_link_already_gone_returns_404`
- `test_post_requirement_role_QA_returns_403` (create is ADMIN/OWNER per docs)
- `test_patch_requirement_role_VIEWER_403`

**Implementation:**

- Schemas in `packages/shared/suitest_shared/schemas/requirement.py`: `RequirementCreate(project_id, title, description="", priority=…)`, `RequirementUpdate`, `RequirementRead`, `RequirementLinkCreate(case_id)`.
- Router at `apps/api/src/suitest_api/routers/requirements.py`. `POST` uses `await generate_public_id(session, "REQ", workspace_id)`.
- Link service uses `RequirementLinkRepository.create(req_id, case_id)` — first does a `SELECT workspace_id FROM requirements WHERE id=:rid` + `SELECT workspace_id FROM test_cases WHERE id=:cid` (both workspace-scoped via session); mismatch raises `CrossWorkspaceLinkError(req_ws, case_ws)`.
- Audit: `requirement.created`, `requirement.updated`, `requirement.soft_deleted`, `requirement.link_created`, `requirement.link_deleted`.
- WS: `requirement.created`, `requirement.linked` (`{requirementId, caseId}`).

**Verification:**

- `pytest apps/api/tests/routers/test_requirements_links.py -q` → green.
- `curl -X POST … /api/v1/requirements -d '{"projectId":…,"title":"Login spec"}'` returns `publicId="REQ-1"` on a fresh workspace.
- `mypy --strict apps/api packages/db` clean.

**Done when:**

- [ ] Requirement CRUD + link CRUD shipped.
- [ ] `CROSS_WORKSPACE_LINK` 400 with exact JSON shape per `docs/API.md §63`.
- [ ] `REQ-N` public id via helper.
- [ ] Role gates correct (create/delete ADMIN+, update QA+).
- [ ] Commit: `feat(api): requirement + link CRUD with cross-workspace guard + REQ public id`.

**Cross-refs:** `docs/API.md §3.x (requirements)`, `docs/DATA_MODEL.md §3.x` (Requirement ORM + RequirementLink), `§8` (public id helper).

---

## Task M1d-7 — `POST /test-cases/bulk-update`

**Goal:** Ship `POST /test-cases/bulk-update` accepting `{action, ids[≤100], payload}` where `action ∈ {delete, move_to_suite, change_priority, add_tags, remove_tags}`. Single transaction, one audit row per case, 100-id cap.

**Out of scope:** Async bulk (queue + progress). FE sticky action bar (M1d-22). Bulk operations on suites or requirements (separate endpoints if ever needed).

**Tests to write** (in `apps/api/tests/routers/test_test_cases_bulk.py`):

- `test_bulk_delete_100_ids_single_transaction_audits_per_case`
- `test_bulk_more_than_100_ids_returns_400_BULK_LIMIT_EXCEEDED_with_received_count`
- `test_bulk_mixed_workspace_ids_returns_403_CROSS_WORKSPACE_BULK_with_offending_ids_no_partial_apply`
- `test_bulk_move_to_suite_updates_suite_id_and_resets_order_in_suite`
- `test_bulk_change_priority_updates_priority_validates_enum_value`
- `test_bulk_add_tags_normalizes_lowercase_dedups_preserves_existing`
- `test_bulk_remove_tags_no_op_if_tag_absent`
- `test_bulk_role_VIEWER_403_role_QA_passes`
- `test_bulk_delete_emits_one_case_deleted_WS_event_per_case`
- `test_bulk_transaction_rolls_back_if_one_case_invalid_action_400_NO_PARTIAL_APPLY`

**Implementation:**

- Pydantic `BulkUpdateRequest` discriminated union per `action`. Use Pydantic v2 `Discriminator(field_name="action")` for typed payloads. Each variant has its own `payload`.
- Router:
  ```
  @router.post("/bulk-update", response_model=BulkUpdateResult, status_code=200,
               dependencies=[Depends(require_role({Role.QA, Role.ADMIN, Role.OWNER}))])
  async def bulk_update_test_cases(body: BulkUpdateRequest, …) -> BulkUpdateResult: …
  ```
- Service single transaction: pre-validate all ids belong to current workspace (one `SELECT id, workspace_id FROM test_cases WHERE id = ANY(:ids)`; mismatch → 403 with offending ids); execute the action; write one audit row per affected case; emit one WS event per case.
- 100-id cap enforced in the Pydantic validator with `Field(max_length=100)`.

**Verification:**

- `pytest apps/api/tests/routers/test_test_cases_bulk.py -q` → green.
- Trace shows single DB transaction span containing all updates.
- `mypy --strict apps/api packages/shared` clean.

**Done when:**

- [ ] All five `action` variants implemented.
- [ ] 100-id cap enforced; mixed-workspace ids 403 with no partial apply.
- [ ] Single transaction, audit-per-case, WS-per-case.
- [ ] Role-gated to QA+.
- [ ] Commit: `feat(api): bulk-update test cases — delete/move/priority/tag-add/remove, 100-id cap, single tx`.

**Cross-refs:** `docs/API.md §3.1` lines 208, 213.

---

## Task M1d-8 — `POST /test-cases/:id/run` ad-hoc shortcut

**Goal:** Ship `POST /test-cases/:id/run` as a thin shortcut over the existing M1c `RunService.create`. Body is empty (or `{}`). Pre-flight re-validates `STEPS_REQUIRE_CODE_IN_ZERO_LLM`. Returns `{runId, publicId, statusUrl, wsRoom}`.

**Out of scope:** Step-level `POST /steps/test-once` (already shipped as a `docs/API.md §209` endpoint or M1d-8a if missing — verify in M1c; if not, add a stub task here). Scheduled cron runs (deferred to M2/M5). Run cancel/rerun (already shipped in M1c — wired to FE in M1d-33).

**Tests to write** (in `apps/api/tests/routers/test_test_cases_run_shortcut.py`):

- `test_post_run_returns_201_with_run_payload_runId_publicId_statusUrl_wsRoom`
- `test_post_run_zero_tier_with_step_missing_code_returns_400_STEPS_REQUIRE_CODE_IN_ZERO_LLM_with_stepIndex` (pre-flight validator)
- `test_post_run_unregistered_mcp_returns_404_MCP_PROVIDER_NOT_REGISTERED`
- `test_post_run_cross_workspace_case_id_returns_404`
- `test_post_run_delegates_to_RunService_create_with_selection_caseId`
- `test_post_run_role_QA_passes_VIEWER_403`
- `test_post_run_emits_run_queued_WS_event_via_M1c_RunService`

**Implementation:**

- Router method on existing `test_cases.py`:
  ```
  @router.post("/{case_id}/run", response_model=AdHocRunResponse, status_code=201,
               dependencies=[Depends(require_role({Role.QA, Role.ADMIN, Role.OWNER}))])
  async def run_now(case_id: str, …) -> AdHocRunResponse: …
  ```
- Service: load case + steps, run `validate_steps` (re-uses M1d-2 validator with current workspace settings), then call `RunService.create(workspace_id=…, project_id=case.project_id, selection=[{"caseId": case_id}], name=f"ad-hoc {case.publicId}", triggered_by=user_id, trigger_kind=RunTriggerKind.AD_HOC)`.
- Response payload includes `statusUrl=f"/api/v1/runs/{run_id}"` and `wsRoom=f"run:{run_id}"`.

**Verification:**

- `pytest apps/api/tests/routers/test_test_cases_run_shortcut.py -q` → green.
- FE-side smoke: M1d-26 "Run now" button calls this and deep-links to `/runs/:id`.
- `mypy --strict apps/api` clean.

**Done when:**

- [ ] Endpoint shipped, role-gated, pre-flight validator runs.
- [ ] Delegates to M1c `RunService.create` with `trigger_kind=AD_HOC`.
- [ ] Response payload shape matches FE contract for M1d-26.
- [ ] Commit: `feat(api): ad-hoc run shortcut POST /test-cases/:id/run delegating to RunService`.

**Cross-refs:** `docs/API.md §3.1` line 204, M1c plan-04 § "Task 11-12" for `RunService.create` signature.

---

## Task M1d-9 — Defects (manual POST/PATCH + sync-external)

**Goal:** Ship `POST /defects` (manual file, `SUIT-N` public id), `PATCH /defects/:id` for status flow (`OPEN → IN_PROGRESS → RESOLVED → CLOSED`; `OPEN → WONT_FIX`; `RESOLVED → OPEN` for reopen), and `POST /defects/:id/sync-external` to force push current state to the configured tracker.

**Out of scope:** Auto-defect filer (M1d-10). External tracker adapters (M1d-12..15). Webhook sync-back (M1d-18). FE interactive cards (M1d-24).

**Tests to write** (in `apps/api/tests/routers/test_defects_crud.py`):

- `test_post_defect_manual_creates_with_SUIT_public_id_via_helper`
- `test_post_defect_with_run_id_test_case_id_links_FKs`
- `test_post_defect_without_run_id_allowed_for_manual_off_run_filing`
- `test_patch_defect_status_OPEN_to_IN_PROGRESS_emits_defect_updated_WS`
- `test_patch_defect_status_to_RESOLVED_sets_resolved_at_utcnow`
- `test_patch_defect_status_to_CLOSED_requires_RESOLVED_first_else_400_INVALID_STATUS_TRANSITION`
- `test_patch_defect_status_to_WONT_FIX_allowed_from_any_non_terminal_state`
- `test_patch_defect_RESOLVED_to_OPEN_clears_resolved_at_reopen_path`
- `test_post_sync_external_with_no_external_tracker_configured_returns_404_NO_DEFAULT_TRACKER`
- `test_post_sync_external_with_jira_configured_calls_JiraAdapter_update_issue` (mock adapter)
- `test_post_sync_external_failure_returns_502_INTEGRATION_UPSTREAM_ERROR_with_provider_in_details`
- `test_defects_writes_role_QA_passes_VIEWER_403`

**Implementation:**

- Pydantic `DefectCreate(title, description, severity, run_id?, test_case_id?, assignee_user_id?)`, `DefectUpdate(status?, severity?, assignee_user_id?, description?)`, `DefectRead`.
- Router `apps/api/src/suitest_api/routers/defects.py` extends M1a read router.
- Service `defect_service.py`:
  - `create(...)` — generate `SUIT-N` via helper; `created_by="user:" + user_id` (not `"system"`); set `agent_diagnosis_kind=None`.
  - `update(...)` — `_validate_status_transition(old, new)`:
    ```
    _ALLOWED = {
      DefectStatus.OPEN: {DefectStatus.IN_PROGRESS, DefectStatus.WONT_FIX, DefectStatus.CLOSED},
      DefectStatus.IN_PROGRESS: {DefectStatus.RESOLVED, DefectStatus.OPEN, DefectStatus.WONT_FIX},
      DefectStatus.RESOLVED: {DefectStatus.CLOSED, DefectStatus.OPEN},
      DefectStatus.CLOSED: set(),  # terminal
      DefectStatus.WONT_FIX: {DefectStatus.OPEN},
    }
    ```
    Set `resolved_at=NOW()` on first transition to RESOLVED; clear on transition out of RESOLVED.
  - `sync_external(defect_id)` — load integration for workspace (`default_for_defects=True`); load adapter via M1d-11 registry; call `adapter.update(defect)`; on error, mark integration `status=error` + emit WS `integration.error`.

**Verification:**

- `pytest apps/api/tests/routers/test_defects_crud.py -q` → green.
- `mypy --strict apps/api packages/shared` clean.

**Done when:**

- [ ] `POST/PATCH /defects` + `POST /defects/:id/sync-external` shipped.
- [ ] Status transition matrix enforced.
- [ ] `resolved_at` flips on RESOLVED transitions.
- [ ] sync-external surfaces upstream errors as 502 with `details.provider`.
- [ ] Audit + WS per write.
- [ ] Commit: `feat(api): defect manual CRUD with status transitions + sync-external delegation`.

**Cross-refs:** `docs/API.md §3.x (defects)`, `docs/DATA_MODEL.md §6` (DefectStatus, Severity), `§3.x` (Defect ORM).

---

## Task M1d-10 — `DefectAutoFiler` + regex `DefectCategorizer` + runner hook

**Goal:** Wire a regex categorizer + auto-filer into the M1c runner `on_run_step_failed(run_step)` hook. On step fail: categorize via regex over `stderr` + `stdout` + assertion message; pick severity from the case's `priority`; INSERT defect with `created_by='system'`, `agent_diagnosis_kind=<one of REGRESSION/FLAKE/INFRA/SPEC_DRIFT/MANUAL_TRIAGE>`; dedup via partial unique index from M1d-1; emit `defect.created` exactly once.

**Out of scope:** AI-driven categorization (M3). Defect linking to git commit (M2+). Slack notification (M1d-15 wires it).

**Tests to write** (in `apps/api/tests/services/test_defect_auto_filer.py`):

- `test_categorizer_regression_keyword_status_changed_returns_REGRESSION` — `"Expected 200 OK, got 500 Internal Server Error"` → `REGRESSION`.
- `test_categorizer_flake_keyword_timeout_or_intermittent_returns_FLAKE` — `"Timeout exceeded while waiting for selector"` → `FLAKE`.
- `test_categorizer_infra_keyword_econnrefused_or_5xx_db_down_returns_INFRA` — `"ECONNREFUSED 127.0.0.1:5432"` → `INFRA`.
- `test_categorizer_spec_drift_when_assertion_path_missing_returns_SPEC_DRIFT` — `"jsonpath $.user.email no match"` → `SPEC_DRIFT`.
- `test_categorizer_unknown_failure_returns_MANUAL_TRIAGE_fallback` — `"Unknown error: panic"` → `MANUAL_TRIAGE`.
- `test_severity_from_case_priority_critical_to_S0_high_to_S1_medium_to_S2_low_to_S3` (using `_SEVERITY_BY_PRIORITY`).
- `test_auto_filer_on_step_fail_inserts_defect_with_created_by_system_and_emits_defect_created_WS_once`
- `test_auto_filer_dedup_second_call_for_same_run_case_returns_None_no_duplicate_row` — proves partial unique idx wins.
- `test_auto_filer_does_not_dedup_against_manual_defect_partial_idx_scopes_system_only`
- `test_auto_filer_writes_audit_action_defect_auto_filed_metadata_kind_severity`
- `test_runner_handler_on_StepOutcome_FAIL_invokes_auto_filer` — patches `DefectAutoFiler.file_for_failed_step` in the runner's step handler; asserts called with `run_step.id`.
- `test_auto_filer_skips_if_workspace_settings_auto_defect_disabled`

**Implementation:**

- Module `apps/api/src/suitest_api/services/defect_auto_filer.py`:
  ```
  @dataclass(frozen=True)
  class CategorizedDefect:
      kind: DiagnosisKind
      severity: Severity
      title: str
      description: str

  _RULES: tuple[tuple[re.Pattern[str], DiagnosisKind], ...] = (
      (re.compile(r"(?i)(econnrefused|connection refused|503 service unavailable|5\d\d.*db|database is starting up)"), DiagnosisKind.INFRA),
      (re.compile(r"(?i)(timeout|exceeded.*deadline|intermittent|flaky)"), DiagnosisKind.FLAKE),
      (re.compile(r"(?i)(expected.*got|status \d+ != \d+|response code mismatch)"), DiagnosisKind.REGRESSION),
      (re.compile(r"(?i)(jsonpath.*no match|header.*missing|schema.*mismatch|selector .* not found)"), DiagnosisKind.SPEC_DRIFT),
  )

  _SEVERITY_BY_PRIORITY: dict[CasePriority, Severity] = {
      CasePriority.CRITICAL: Severity.S0,
      CasePriority.HIGH: Severity.S1,
      CasePriority.MEDIUM: Severity.S2,
      CasePriority.LOW: Severity.S3,
  }

  class DefectCategorizer:
      def categorize(self, *, stderr: str, stdout: str, assertion_message: str | None) -> DiagnosisKind:
          blob = "\n".join(filter(None, [stderr, stdout, assertion_message or ""]))
          for pattern, kind in _RULES:
              if pattern.search(blob): return kind
          return DiagnosisKind.MANUAL_TRIAGE

  class DefectAutoFiler:
      def __init__(self, *, defect_repo, audit_session_factory, ws_publisher, categorizer): ...
      async def file_for_failed_step(self, run_step_id: str) -> str | None:
          # 1. Load run_step + run + case (with priority).
          # 2. Categorize → DiagnosisKind.
          # 3. severity = _SEVERITY_BY_PRIORITY[case.priority].
          # 4. Build title (`f"[Auto] {case.public_id} failed: {kind.value}"`) + description (templated, includes step idx, stderr first 200 chars, last assertion).
          # 5. INSERT defect created_by='system', kind, severity; catch IntegrityError on partial idx → return None.
          # 6. Write audit + emit defect.created WS.
          # 7. Return defect_id.
  ```
- Runner DI in `apps/runner/src/suitest_runner/deps.py`: expose a singleton `DefectAutoFiler`; the runner step handler imports it.
- Runner handler hook at `apps/runner/src/suitest_runner/handlers/step_handler.py`: on `StepOutcome.FAIL`, schedule `defect_auto_filer.file_for_failed_step(run_step.id)` via `asyncio.create_task` (fire-and-forget; failure is logged but not propagated to runner).

**Verification:**

- `pytest apps/api/tests/services/test_defect_auto_filer.py -q` → green (>= one test per rule + dedup + WS + audit).
- `pytest apps/runner/tests/handlers/test_step_handler_defect_hook.py -q` → green.
- `mypy --strict apps/api apps/runner` clean.

**Done when:**

- [ ] `DefectAutoFiler` + `DefectCategorizer` modules added.
- [ ] >= 1 test per `_RULES` row + fallback + severity matrix.
- [ ] Dedup partial idx test green.
- [ ] Runner hook wired; failures don't break runs.
- [ ] WS event emitted exactly once.
- [ ] Commit: `feat(api,runner): rule-based defect categorizer + auto-filer wired to runner step-failed hook`.

**Cross-refs:** `docs/DATA_MODEL.md §6` (`DiagnosisKind` canonical set line ~1366), M1c plan-04 § Task 12 (runner step handler).

---

## Task M1d-11 — `IssueTrackerAdapter` Protocol + registry + contract test

**Goal:** Define the integration adapter Protocol surface + an `AdapterRegistry`, plus a contract test that **must pass with zero registered adapters** so M1d-12..15 can each add their concrete adapter in isolation.

**Out of scope:** Any concrete adapter (those are M1d-12..15). FE integrations page (M1d-25).

**Tests to write** (in `apps/api/tests/integrations/test_adapter_protocol_contract.py`):

- `test_protocol_defines_required_methods` — assert the Protocol has `create_external_issue`, `update_external_issue`, `transition_status`, `map_external_status_to_defect_status`, `test_connection`.
- `test_registry_register_and_get_by_kind`
- `test_registry_get_unknown_kind_raises_AdapterNotRegistered`
- `test_registry_zero_iterations_with_no_adapters_passes` (sanity — contract test runs cleanly when concrete adapters absent).
- `test_contract_test_each_registered_adapter_implements_protocol` — for each registered adapter, `isinstance(adapter, IssueTrackerAdapter)` passes (since Protocol is `@runtime_checkable`).
- `test_external_issue_pydantic_model_round_trips`

**Implementation:**

- Module `apps/api/src/suitest_api/integrations/base.py`:
  ```
  from typing import Protocol, runtime_checkable

  class ExternalIssue(BaseModel):
      external_id: str
      external_key: str  # e.g. "PROJ-123"
      external_url: str
      status: str
      raw: dict[str, Any] = Field(default_factory=dict)

  class ExternalIssueInput(BaseModel):
      defect_id: str
      title: str
      description: str
      severity: Severity
      labels: list[str] = []
      assignee_external_id: str | None = None

  @runtime_checkable
  class IssueTrackerAdapter(Protocol):
      kind: str  # "jira" | "linear" | "github"
      async def test_connection(self) -> bool: ...
      async def create_external_issue(self, body: ExternalIssueInput) -> ExternalIssue: ...
      async def update_external_issue(self, external_key: str, body: ExternalIssueInput) -> ExternalIssue: ...
      async def transition_status(self, external_key: str, new_status: DefectStatus) -> None: ...
      def map_external_status_to_defect_status(self, external_status: str) -> DefectStatus | None: ...
  ```
- Module `apps/api/src/suitest_api/integrations/registry.py`:
  ```
  class AdapterRegistry:
      def __init__(self) -> None: self._by_kind: dict[str, IssueTrackerAdapter] = {}
      def register(self, adapter: IssueTrackerAdapter) -> None: ...
      def get(self, kind: str) -> IssueTrackerAdapter: ...
      def list_kinds(self) -> list[str]: ...
  ```
- Module `__init__.py` for the new package stays empty (no barrel).
- Wire empty registry into `apps/api/src/suitest_api/main.py` lifespan (`app.state.adapter_registry = AdapterRegistry()`).

**Verification:**

- `pytest apps/api/tests/integrations/test_adapter_protocol_contract.py -q` → green with zero concrete adapters.
- `mypy --strict apps/api` clean (Protocol + `@runtime_checkable`).

**Done when:**

- [ ] `IssueTrackerAdapter` Protocol + `AdapterRegistry` shipped.
- [ ] Contract test passes with zero adapters.
- [ ] Wired into app lifespan.
- [ ] Commit: `feat(integrations): IssueTrackerAdapter protocol + adapter registry + contract test scaffold`.

**Cross-refs:** `docs/superpowers/specs/2026-05-30-m1d-manual-tcm-writes.md §6` ("Architecture / data model touchpoints"), `docs/DATA_MODEL.md §6` (Severity, DefectStatus).

---

## Task M1d-12 — `JiraAdapter` (thin wrapper over bundled `jirac-mcp@jira-mcp-v2.0.1`)

**Goal:** Implement `JiraAdapter` as a thin wrapper over the bundled `jirac-mcp` Rust binary (registered in `mcp_providers` by M1d-1). Owns AES-GCM encryption of Jira credentials and per-invocation env injection via `pool.acquire(provider, env_overrides=…)`. No Python `httpx` Jira REST. No OAuth.

**Out of scope:** Webhook sync-back (M1d-18). FE connect dialog (M1d-25). Jira PROJECT picker UI. Caching of `jira_issue_transitions_list` results.

**Tests to write** (in `apps/api/tests/integrations/test_jira_adapter.py`):

- `test_jira_adapter_test_connection_invokes_jira_account_view_or_jira_api_request_whoami_via_mocked_mcp_session`
- `test_jira_adapter_create_external_issue_calls_jira_issue_create_via_mock_pool_with_env_overrides_JIRA_URL_JIRA_EMAIL_JIRA_TOKEN_JIRA_AUTH_TYPE`
- `test_jira_adapter_update_external_issue_calls_jira_issue_update`
- `test_jira_adapter_transition_status_lists_transitions_then_calls_jira_issue_transition_with_id_matching_target_status`
- `test_jira_adapter_map_external_status_to_defect_status_uses_workspace_settings_jira_status_map`
- `test_jira_adapter_severity_mapped_to_priority_field_python_side` — assert `Severity.S0 → "Highest"`, S1→"High", S2→"Medium", S3→"Low".
- `test_jira_adapter_authentication_cloud_api_token_passes_basic_email_token_env`
- `test_jira_adapter_authentication_datacenter_pat_passes_bearer_env`
- `test_jira_adapter_does_NOT_write_to_home_config_jira_config_toml` — assert no file written via fs spy.
- `test_jira_adapter_mcp_pool_acquire_called_with_provider_name_jirac_mcp_and_env_overrides_dict`
- `test_jira_adapter_mcp_tool_failure_bubbles_as_IntegrationUpstreamError_with_provider_jira_in_details`
- `test_jira_adapter_jira_issue_view_used_for_post_create_round_trip_validation`

**Implementation:**

- Module `apps/api/src/suitest_api/integrations/jira_adapter.py`:
  ```
  class JiraAdapter:
      kind = "jira"
      def __init__(self, *, integration: Integration, mcp_pool: McpPool, crypto: AesGcmCrypto): ...
      async def _env_overrides(self) -> dict[str, str]:
          secrets = self.crypto.decrypt(self.integration.secrets_encrypted)
          return {"JIRA_URL": secrets["url"],
                  "JIRA_EMAIL": secrets["email"],
                  "JIRA_TOKEN": secrets["token"],
                  "JIRA_AUTH_TYPE": secrets["auth_type"]}  # cloud_api_token | datacenter_pat | datacenter_basic
      async def _invoke(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
          provider = self.registry.get(workspace_id, "jirac-mcp")
          async with self.mcp_pool.acquire(provider, env_overrides=await self._env_overrides()) as sess:
              result = await sess.call_tool(tool, args, timeout_seconds=provider.call_timeout_seconds)
              return json.loads(result.stdout)
      async def create_external_issue(self, body): return self._to_external(await self._invoke("jira_issue_create", {...}))
      async def update_external_issue(self, key, body): return self._to_external(await self._invoke("jira_issue_update", {...}))
      async def transition_status(self, key, new_status):
          tids = await self._invoke("jira_issue_transitions_list", {"issue_key": key})
          tid = self._pick_transition(tids, new_status)
          await self._invoke("jira_issue_transition", {"issue_key": key, "transition_id": tid, "confirm": True})
      def map_external_status_to_defect_status(self, ext): ...
      async def test_connection(self):
          await self._invoke("jira_api_request", {"method": "GET", "path": "/rest/api/3/myself"})
          return True
  ```
- Status map default (Python-side, overridable per integration):
  ```
  _DEFAULT_JIRA_STATUS_TO_DEFECT = {
      "Open": DefectStatus.OPEN, "To Do": DefectStatus.OPEN,
      "In Progress": DefectStatus.IN_PROGRESS,
      "Done": DefectStatus.RESOLVED, "Resolved": DefectStatus.RESOLVED,
      "Closed": DefectStatus.CLOSED,
      "Won't Do": DefectStatus.WONT_FIX, "Wontfix": DefectStatus.WONT_FIX,
  }
  ```
- Severity map: `Severity.S0 → "Highest"`, `S1 → "High"`, `S2 → "Medium"`, `S3 → "Low"`.
- Register adapter in `main.py` lifespan: `registry.register(JiraAdapter(…))` after M1d-11 registry exists.
- **Bundled provider config** at `packages/mcp/suitest_mcp/bundled/jira.py`:
  ```
  JIRA_SPEC = McpProviderConfig(
      id="builtin:jirac-mcp",
      workspace_id=None,  # bundled/global — DB column is nullable post-M1d-1
      name="jirac-mcp",
      kind="issue-tracker",
      transport=McpTransport.STDIO,
      command=["jirac-mcp", "serve", "--transport", "stdio"],
      env={},  # env injected per invocation
      config_json={"version_pin": "jira-mcp-v2.0.1"},
      max_sessions=2,
      spawn_timeout_seconds=10.0,
      call_timeout_seconds=30.0,
  )
  ```
  Add to `BUILTIN_SPECS` list in `packages/mcp/suitest_mcp/providers/builtin_specs.py`.
- **Dockerfile** at `infra/docker/Dockerfile.api` (and `Dockerfile.runner`) — add multi-stage download:
  ```
  FROM alpine:3.19 AS jira-mcp-downloader
  ARG TARGETARCH
  ARG JIRA_MCP_VERSION=jira-mcp-v2.0.1
  RUN apk add --no-cache curl
  RUN if [ "$TARGETARCH" = "amd64" ]; then ARCH=x86_64; else ARCH=aarch64; fi && \
      curl -fL "https://github.com/mulhamna/jira-commands/releases/download/${JIRA_MCP_VERSION}/jirac-mcp-linux-${ARCH}.tar.gz" \
        | tar -xz -C /tmp && \
      install -m0755 "/tmp/jirac-mcp-linux-${ARCH}" /usr/local/bin/jirac-mcp

  FROM python:3.12-slim AS final
  COPY --from=jira-mcp-downloader /usr/local/bin/jirac-mcp /usr/local/bin/jirac-mcp
  ```
  Match the prototype layout in `Dockerfile.mcp-prototype`.
- Update `docs/MCP_PLUGINS.md §3` bundled table — add `jirac-mcp | issue-tracker | stdio | EXTERNAL_TOOL | Jira issue tracker | cloud-token / PAT`.
- Update `docs/DEPLOYMENT.md §15` air-gap bundle list with binary size + URL.

**Verification:**

- `pytest apps/api/tests/integrations/test_jira_adapter.py -q` → green.
- Built image runs `jirac-mcp --version` successfully (smoke step in CI).
- `mypy --strict apps/api packages/mcp` clean.

**Done when:**

- [ ] `JiraAdapter` shipped using `packages/mcp/client` with env injection.
- [ ] Bundled provider config + Dockerfile stage land.
- [ ] Auth: cloud_api_token + datacenter_pat + datacenter_basic supported; no OAuth.
- [ ] Status map + severity map Python-side.
- [ ] Mocked MCP session tests cover create/update/transition/test_connection.
- [ ] `docs/MCP_PLUGINS.md §3` + `docs/DEPLOYMENT.md §15` updated.
- [ ] Commit: `feat(integrations,mcp): Jira adapter as thin wrapper over bundled jirac-mcp + Dockerfile bundle stage`.

**Cross-refs:** `docs/superpowers/specs/2026-05-30-m1d-manual-tcm-writes.md §M1d-12` (canonical decisions list), `docs/MCP_PLUGINS.md §3` + `§5.3`, `docs/DEPLOYMENT.md §15`, `Dockerfile.mcp-prototype`, `docs/superpowers/specs/2026-05-30-m1d-mcp-bundling-prototype.md`.

---

## Task M1d-13 — `LinearAdapter` (httpx GraphQL, stays non-MCP)

**Goal:** Implement `LinearAdapter` using `httpx.AsyncClient` against Linear's GraphQL API (`https://api.linear.app/graphql`). PAT (Personal Access Token, `Authorization: <token>` no Bearer prefix per Linear docs). Maps state-name → DefectStatus and Severity → priority 1..4.

**Out of scope:** Linear OAuth (PAT-only for v1.0). Linear webhook sync-back (out of M1d scope — would be added with M5 OAuth). Linear MCP wrapping (deferred to M2 per spec).

**Tests to write** (in `apps/api/tests/integrations/test_linear_adapter.py`, using `respx` + VCR cassette):

- `test_linear_test_connection_runs_viewer_query`
- `test_linear_create_external_issue_runs_issueCreate_mutation_with_teamId_title_description_priority`
- `test_linear_update_external_issue_runs_issueUpdate_mutation`
- `test_linear_transition_status_resolves_state_id_from_workflow_states_then_issueUpdate_stateId`
- `test_linear_map_external_status_default_map_passes_Triage_to_OPEN_InProgress_to_IN_PROGRESS_Done_to_RESOLVED_Canceled_to_WONT_FIX`
- `test_linear_severity_to_priority_S0_to_1_S1_to_2_S2_to_3_S3_to_4`
- `test_linear_authentication_header_just_PAT_no_Bearer_prefix`
- `test_linear_GraphQL_error_response_bubbles_as_IntegrationUpstreamError`
- `test_linear_httpx_timeout_10s_enforced`
- `test_linear_team_id_loaded_from_integration_config_json`

**Implementation:**

- Module `apps/api/src/suitest_api/integrations/linear_adapter.py`:
  ```
  class LinearAdapter:
      kind = "linear"
      _BASE = "https://api.linear.app/graphql"
      def __init__(self, *, integration, crypto, http_client: httpx.AsyncClient): ...
      async def _gql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
          token = self.crypto.decrypt(self.integration.secrets_encrypted)["pat"]
          r = await self.http.post(self._BASE, headers={"Authorization": token, "Content-Type": "application/json"},
                                   json={"query": query, "variables": variables})
          r.raise_for_status()
          data = r.json()
          if "errors" in data: raise IntegrationUpstreamError("linear", data["errors"])
          return data["data"]
  ```
- Severity → priority: `S0→1, S1→2, S2→3, S3→4`.
- Single `httpx.AsyncClient(timeout=10.0)` shared via DI from app lifespan.

**Verification:**

- `pytest apps/api/tests/integrations/test_linear_adapter.py -q` → green (respx cassettes).
- `mypy --strict apps/api` clean.

**Done when:**

- [ ] `LinearAdapter` shipped using `httpx`.
- [ ] State + severity maps Python-side.
- [ ] Cassettes committed.
- [ ] Adapter registered in lifespan.
- [ ] Commit: `feat(integrations): Linear adapter via httpx GraphQL with state/priority maps`.

**Cross-refs:** `docs/superpowers/specs/2026-05-30-m1d-manual-tcm-writes.md §M1d-13`.

---

## Task M1d-14 — `GitHubAdapter` (thin wrapper over bundled `github-mcp-server@v1.1.2`)

**Goal:** Implement `GitHubAdapter` as a thin wrapper over bundled `github-mcp-server` (Go binary). Owns GitHub App installation token mint + 50-min cache + AES-GCM stored App private key. Tool execution delegated via `packages/mcp/client` with env `GITHUB_PERSONAL_ACCESS_TOKEN=<installation-token>` + `GITHUB_TOOLSETS=issues` (trim surface).

**Out of scope:** GitHub PR review automation. GitHub Actions integration. GitHub OAuth (App-only). Workflow runs / checks API (not needed for issue filing).

**Tests to write** (in `apps/api/tests/integrations/test_github_adapter.py`):

- `test_github_mint_installation_token_calls_app_installations_endpoint_signs_jwt_with_app_private_key_PEM`
- `test_github_installation_token_cached_50_minutes_subsequent_calls_no_new_mint`
- `test_github_installation_token_expired_after_50_min_remints`
- `test_github_create_external_issue_calls_issue_write_via_mocked_mcp_pool_with_env_overrides_GITHUB_PERSONAL_ACCESS_TOKEN_GITHUB_TOOLSETS`
- `test_github_add_comment_calls_add_issue_comment`
- `test_github_severity_label_applied_python_side_creates_severity_S0_label_first`
- `test_github_map_external_status_open_to_OPEN_closed_to_CLOSED_default_map`
- `test_github_authentication_uses_App_installation_not_PAT`
- `test_github_test_connection_pings_installations_self_or_viewer`
- `test_github_environment_variable_GITHUB_TOOLSETS_issues_trims_surface`
- `test_github_mcp_tool_failure_bubbles_IntegrationUpstreamError_provider_github`

**Implementation:**

- Module `apps/api/src/suitest_api/integrations/github_adapter.py`:
  ```
  class GitHubAdapter:
      kind = "github"
      def __init__(self, *, integration, mcp_pool, registry, crypto, http_client): ...
      async def _installation_token(self) -> str:
          cached = await self._cache.get(self._cache_key)
          if cached: return cached
          jwt = self._sign_app_jwt(self.integration.app_id, self.integration.private_key_pem)
          r = await self.http.post(
              f"https://api.github.com/app/installations/{self.integration.installation_id}/access_tokens",
              headers={"Authorization": f"Bearer {jwt}", "Accept": "application/vnd.github+json"})
          r.raise_for_status()
          tok = r.json()["token"]
          await self._cache.set(self._cache_key, tok, ttl=50*60)  # 50 min < 60 min upstream TTL
          return tok
      def _sign_app_jwt(self, app_id, pem):
          import jwt
          now = int(time.time())
          return jwt.encode({"iat": now-30, "exp": now+540, "iss": str(app_id)}, pem, algorithm="RS256")
      async def _invoke(self, tool, args):
          provider = self.registry.get(workspace_id, "github-mcp")
          env = {"GITHUB_PERSONAL_ACCESS_TOKEN": await self._installation_token(),
                 "GITHUB_TOOLSETS": "issues"}
          async with self.mcp_pool.acquire(provider, env_overrides=env) as sess:
              r = await sess.call_tool(tool, args, timeout_seconds=provider.call_timeout_seconds)
              return json.loads(r.stdout)
      async def create_external_issue(self, body):
          # Use issue_write to create + add severity label (Python-side concat).
          issue = await self._invoke("issue_write", {"action": "create", "owner": …, "repo": …,
                                                    "title": body.title, "body": body.description,
                                                    "labels": ["suitest", f"severity:{body.severity.value.lower()}"]})
          return self._to_external(issue)
      ...
  ```
- Env vars (per § Canonical decision #11): `SUITEST_GITHUB_APP_ID` (numeric), `SUITEST_GITHUB_APP_PRIVATE_KEY_PEM` (RSA PEM). App private key passed in as plaintext if from env, AES-GCM at-rest if stored in `integrations.secrets_encrypted`.
- Bundled provider config at `packages/mcp/suitest_mcp/bundled/github.py`:
  ```
  GITHUB_SPEC = McpProviderConfig(
      id="builtin:github-mcp", workspace_id=None, name="github-mcp",  # bundled/global
      kind="issue-tracker", transport=McpTransport.STDIO,
      command=["github-mcp-server", "stdio", "--toolsets", "issues"],
      env={}, config_json={"version_pin": "v1.1.2"},
      max_sessions=2, spawn_timeout_seconds=10.0, call_timeout_seconds=30.0,
  )
  ```
- Dockerfile stage at `infra/docker/Dockerfile.api` + `Dockerfile.runner`:
  ```
  FROM alpine:3.19 AS gh-mcp-downloader
  ARG TARGETARCH
  ARG GH_MCP_VERSION=v1.1.2
  RUN apk add --no-cache curl
  RUN if [ "$TARGETARCH" = "amd64" ]; then ARCH=x86_64; else ARCH=arm64; fi && \
      curl -fL "https://github.com/github/github-mcp-server/releases/download/${GH_MCP_VERSION}/github-mcp-server_Linux_${ARCH}.tar.gz" \
        | tar -xz -C /tmp && \
      install -m0755 "/tmp/github-mcp-server" /usr/local/bin/github-mcp-server

  FROM python:3.12-slim AS final
  COPY --from=gh-mcp-downloader /usr/local/bin/github-mcp-server /usr/local/bin/github-mcp-server
  ```
- Update `docs/MCP_PLUGINS.md §3` bundled table — add `github-mcp | issue-tracker | stdio | EXTERNAL_TOOL | GitHub Issues + labels | github-app-installation-token / PAT`.
- Update `docs/DEPLOYMENT.md §15`.

**Verification:**

- `pytest apps/api/tests/integrations/test_github_adapter.py -q` → green.
- Built image runs `github-mcp-server --version` successfully in CI.
- `mypy --strict apps/api packages/mcp` clean.

**Done when:**

- [ ] `GitHubAdapter` shipped, using `packages/mcp/client` with `GITHUB_TOOLSETS=issues`.
- [ ] App installation token mint + 50-min cache Python-side.
- [ ] Bundled provider config + Dockerfile stage land.
- [ ] Adapter registered in lifespan.
- [ ] `docs/MCP_PLUGINS.md §3` + `docs/DEPLOYMENT.md §15` updated.
- [ ] Commit: `feat(integrations,mcp): GitHub adapter as thin wrapper over bundled github-mcp-server + Dockerfile bundle stage`.

**Cross-refs:** `docs/superpowers/specs/2026-05-30-m1d-manual-tcm-writes.md §M1d-14`, `Dockerfile.mcp-prototype`.

---

## Task M1d-15 — `SlackAdapter` (httpx incoming webhook) + ARQ notification job

**Goal:** Implement `SlackAdapter` posting Block Kit messages to a Slack Incoming Webhook URL (one per integration). Wires into `DefectAutoFiler` via an ARQ job `send_slack_notification` with exponential backoff retry (5 attempts).

**Out of scope:** Slack OAuth app w/ interactive buttons (deferred to M5 per spec). Slack DM. Slack channel discovery.

**Tests to write** (in `apps/api/tests/integrations/test_slack_adapter.py`, `respx`):

- `test_slack_test_connection_posts_blocks_to_webhook_url_with_suitest_test_message`
- `test_slack_post_defect_block_kit_message_includes_severity_color_S0_red_S1_amber_S2_yellow_S3_green`
- `test_slack_post_defect_includes_defect_publicId_title_link_back_to_suitest_run`
- `test_slack_arq_job_send_slack_notification_exp_backoff_5_attempts`
- `test_slack_webhook_4xx_response_bubbles_IntegrationUpstreamError`
- `test_slack_webhook_429_triggers_retry_not_immediate_failure`
- `test_DefectAutoFiler_invokes_send_slack_notification_when_slack_integration_default_for_notifications_true`
- `test_DefectAutoFiler_skips_slack_when_no_slack_integration_configured`
- `test_slack_block_kit_payload_validates_against_slack_schema_sanity_check`

**Implementation:**

- Module `apps/api/src/suitest_api/integrations/slack_adapter.py`:
  ```
  class SlackAdapter:
      kind = "slack"
      _SEVERITY_COLOR = {Severity.S0: "#dc2626", Severity.S1: "#f59e0b",
                         Severity.S2: "#facc15", Severity.S3: "#22c55e"}
      def __init__(self, *, integration, crypto, http_client): ...
      async def test_connection(self):
          await self.post_blocks([{"type": "section",
              "text": {"type": "mrkdwn", "text": "*Suitest connection test* (you can disconnect this integration any time)."}}])
          return True
      async def post_defect(self, defect: DefectRead) -> None: ...
      async def post_blocks(self, blocks: list[dict]) -> None:
          url = self.crypto.decrypt(self.integration.secrets_encrypted)["webhook_url"]
          r = await self.http.post(url, json={"blocks": blocks}, timeout=10.0)
          r.raise_for_status()
  ```
- ARQ job at `apps/runner/src/suitest_runner/jobs/slack_notification.py`:
  ```
  async def send_slack_notification(ctx, *, integration_id: str, defect_id: str) -> None: ...
  # WorkerSettings.functions += [send_slack_notification]
  # WorkerSettings.job_timeout = 30; .max_tries = 5
  ```
- `DefectAutoFiler.file_for_failed_step` calls `arq_pool.enqueue_job("send_slack_notification", integration_id=…, defect_id=…)` for the first slack integration with `default_for_notifications=True`.

**Verification:**

- `pytest apps/api/tests/integrations/test_slack_adapter.py -q` → green.
- `mypy --strict apps/api apps/runner` clean.

**Done when:**

- [ ] `SlackAdapter` + ARQ job shipped.
- [ ] Block Kit + severity color map.
- [ ] DefectAutoFiler wired (test passes).
- [ ] Exp backoff retry tested via respx + ARQ test harness.
- [ ] Commit: `feat(integrations,runner): Slack adapter + ARQ send_slack_notification with exp backoff`.

**Cross-refs:** `docs/superpowers/specs/2026-05-30-m1d-manual-tcm-writes.md §M1d-15`.

---

## Task M1d-16 — `POST /webhooks/github` (HMAC + gating-suite trigger + Redis dedup)

**Goal:** Ship the GitHub webhook receiver: HMAC-sha256 verify (constant-time), supports `ping` → 200, `push`, `pull_request.opened/synchronize/reopened` → enqueue a gating-suite run. Run dedup via Redis `SETNX dedup:run:{project_id}:{commit_sha}:{trigger}` with 60s TTL.

**Out of scope:** GitHub Actions integration. GitHub deployments API. GitHub Checks API write-back (deferred to M2+). GitHub OAuth.

**Tests to write** (in `apps/api/tests/routers/test_webhooks_github.py`):

- `test_github_ping_returns_200_ok`
- `test_github_push_with_valid_hmac_enqueues_gating_run`
- `test_github_push_with_invalid_hmac_returns_401_constant_time_compare`
- `test_github_push_with_unsigned_request_returns_401`
- `test_github_pull_request_opened_synchronize_reopened_enqueues_gating_run`
- `test_github_pull_request_closed_returns_200_no_run`
- `test_github_unknown_event_returns_200_no_run`
- `test_github_no_gating_suite_no_smoke_tagged_returns_200_ignored_true_reason_no_gating_suite`
- `test_github_gating_suite_id_set_enqueues_run_with_that_suite_id`
- `test_github_smoke_tag_fallback_enqueues_run_with_smoke_tagged_cases_when_no_gating_suite_id`
- `test_github_redis_setnx_dedup_60s_second_call_with_same_project_commit_trigger_returns_200_ignored_true_reason_dedup_hit`
- `test_github_dedup_key_format_dedup_run_project_id_commit_sha_trigger`
- `test_github_per_workspace_secret_lookup_one_tenants_secret_cannot_replay_another`

**Implementation:**

- Router at `apps/api/src/suitest_api/routers/webhooks_github.py`:
  ```
  @router.post("/webhooks/github", status_code=200)
  async def receive_github(request: Request, x_hub_signature_256: Annotated[str | None, Header()] = None,
                            x_github_event: Annotated[str | None, Header()] = None,
                            x_github_delivery: Annotated[str | None, Header()] = None,
                            …): ...
  ```
- HMAC: `expected = "sha256=" + hmac.new(secret, body_bytes, sha256).hexdigest()`; `hmac.compare_digest(expected, x_hub_signature_256)`. On mismatch → `401`.
- Resolve workspace via `X-GitHub-Hook-Installation-Target-ID` header (App installation) OR via the integration secret discriminator if PAT-based.
- Event routing:
  - `ping` → 200.
  - `push` → enqueue run for `project.gating_suite_id` or `smoke`-tagged cases.
  - `pull_request` with `action ∈ {opened, synchronize, reopened}` → enqueue run.
- Run dedup helper in `apps/api/src/suitest_api/services/webhook_dedup.py`:
  ```
  async def setnx_dedup(redis: redis.asyncio.Redis, *, project_id: str, commit_sha: str, trigger: str,
                         ttl_seconds: int = 60) -> bool:
      key = f"dedup:run:{project_id}:{commit_sha}:{trigger}"
      return await redis.set(name=key, value="1", nx=True, ex=ttl_seconds)
  ```
  Returns `True` on first call, `False` on dedup hit.
- Gating-suite resolver:
  ```
  async def resolve_gating_selection(...) -> list[dict] | None:
      if project.gating_suite_id:
          return [{"suiteId": project.gating_suite_id}]
      smoke_case_ids = await TestCaseRepository.list_ids_by_tag(project_id, "smoke")
      if smoke_case_ids: return [{"caseId": cid} for cid in smoke_case_ids]
      return None  # → 200 ignored
  ```
- Enqueue via `RunService.create(trigger_kind=RunTriggerKind.WEBHOOK_GITHUB, commit_sha=…, …)`.
- Audit row: `webhook.github.received`.

**Verification:**

- `pytest apps/api/tests/routers/test_webhooks_github.py -q` → green.
- Manual `curl -X POST … /api/v1/webhooks/github` with sample push payload + valid HMAC → 200 + run enqueued.
- `mypy --strict apps/api` clean.

**Done when:**

- [ ] `POST /webhooks/github` shipped with HMAC + dedup + gating-suite + smoke fallback.
- [ ] Q4 default `200 {ignored: true}` on no gating.
- [ ] Per-workspace secret prevents cross-tenant replay.
- [ ] Commit: `feat(api): GitHub webhook receiver with HMAC + gating-suite trigger + Redis dedup`.

**Cross-refs:** `docs/API.md §3.x (webhooks)`, `docs/DATA_MODEL.md §3.6` (Run dedup note).

---

## Task M1d-17 — `POST /webhooks/gitlab` (X-Gitlab-Token verify + push + MR scaffolding)

**Goal:** Ship the GitLab webhook receiver: `X-Gitlab-Token` constant-time verify, supports `Push Hook` + `Merge Request Hook (opened|reopened|updated)` → gating-suite run, otherwise 200 ignored.

**Out of scope:** GitLab CI integration. GitLab deployments. GitLab webhook secret rotation UI.

**Tests to write** (in `apps/api/tests/routers/test_webhooks_gitlab.py`):

- `test_gitlab_push_hook_valid_token_enqueues_run`
- `test_gitlab_token_mismatch_returns_401_constant_time`
- `test_gitlab_unsigned_returns_401`
- `test_gitlab_merge_request_opened_reopened_updated_enqueues_run`
- `test_gitlab_unknown_event_kind_returns_200_no_run`
- `test_gitlab_no_gating_returns_200_ignored_true_reason_no_gating_suite`
- `test_gitlab_redis_setnx_dedup_60s_second_call_no_op`
- `test_gitlab_per_workspace_token_lookup`

**Implementation:**

- Router at `apps/api/src/suitest_api/routers/webhooks_gitlab.py` mirroring M1d-16 layout.
- Token verify: `hmac.compare_digest(x_gitlab_token, expected_secret)` (GitLab uses plain shared secret comparison).
- Event routing: `Push Hook` + `Merge Request Hook` (`object_attributes.action ∈ {open, reopen, update}`).
- Reuse `setnx_dedup` + `resolve_gating_selection` from M1d-16.
- Audit row: `webhook.gitlab.received`.

**Verification:**

- `pytest apps/api/tests/routers/test_webhooks_gitlab.py -q` → green.

**Done when:**

- [ ] `POST /webhooks/gitlab` shipped.
- [ ] Token verify + dedup + gating-suite.
- [ ] Commit: `feat(api): GitLab webhook receiver with token verify + push/MR gating trigger`.

**Cross-refs:** `docs/API.md §3.x (webhooks)`.

---

## Task M1d-18 — `POST /webhooks/jira` (issue_updated status sync-back)

**Goal:** Ship Jira webhook receiver: on `jira:issue_updated`, find the local defect by `external_id`, call `JiraAdapter.map_external_status_to_defect_status` on the new status, update local defect status via `DefectService.update_from_external`, write audit `defect.status_synced_from_jira`.

**Out of scope:** Jira webhook subscription provisioning (manual user setup in Jira admin). Jira issue_created sync-back. Jira comment sync-back.

**Tests to write** (in `apps/api/tests/routers/test_webhooks_jira.py`):

- `test_jira_issue_updated_event_finds_local_defect_by_external_id_and_updates_status`
- `test_jira_event_for_unknown_external_id_returns_200_no_op`
- `test_jira_event_with_unmapped_status_logs_warning_returns_200_no_update`
- `test_jira_per_workspace_secret_lookup_constant_time_compare`
- `test_jira_audit_row_action_defect_status_synced_from_jira`
- `test_jira_emits_defect_updated_WS_event_to_workspace_room`
- `test_jira_no_local_change_when_status_already_matches_idempotent`
- `test_jira_dedup_via_jira_changelog_id_60s_TTL_replay_no_op`

**Implementation:**

- Router at `apps/api/src/suitest_api/routers/webhooks_jira.py`.
- Body validator (Pydantic `JiraIssueUpdatedEvent`): captures `webhookEvent`, `issue.key`, `changelog.items[].field=='status'`, new value.
- Service `defect_service.update_from_external(workspace_id, external_id, new_status_str)` — calls `JiraAdapter.map_external_status_to_defect_status` (per integration row); on `None`, log warn + no-op.
- Dedup via Redis `SETNX dedup:jira:webhook:{workspace_id}:{issue_key}:{changelog_id}` 60s TTL.

**Verification:**

- `pytest apps/api/tests/routers/test_webhooks_jira.py -q` → green.

**Done when:**

- [ ] `POST /webhooks/jira` shipped.
- [ ] Issue-updated status sync-back wired through M1d-12 adapter map.
- [ ] Audit + WS per update.
- [ ] Dedup idempotency.
- [ ] Commit: `feat(api): Jira webhook receiver for issue_updated status sync-back`.

**Cross-refs:** `docs/superpowers/specs/2026-05-30-m1d-manual-tcm-writes.md §M1d-18`.

---

## Task M1d-19 — Integration CRUD + test + sync (AES-GCM, no secret echo)

**Goal:** Ship `POST/PATCH/DELETE /integrations/:id` + `POST /integrations/:id/test` + `POST /integrations/:id/sync` + pre-save `/integrations/jira/test-connection` + `/integrations/github/test-connection`. All secrets AES-GCM at rest, never echoed in `IntegrationRead`. ADMIN/OWNER gated.

**Out of scope:** OAuth flows for any provider (Jira PAT-only per spec; GitHub App via env). FE connect dialog (M1d-25). Integration health probes (background — deferred to M5).

**Tests to write** (in `apps/api/tests/routers/test_integrations_crud.py`):

- `test_post_integration_jira_persists_with_secrets_aes_gcm_encrypted_at_rest`
- `test_post_integration_response_never_echoes_secret_material`
- `test_patch_integration_partial_secret_update_preserves_unchanged_fields`
- `test_delete_integration_marks_inactive_does_not_hard_delete_for_audit_trail`
- `test_post_integration_test_jira_invokes_JiraAdapter_test_connection`
- `test_post_integration_sync_jira_re_fetches_workflow_statuses_caches_in_config_json`
- `test_post_integrations_jira_test_connection_does_not_persist_a_row`
- `test_post_integrations_github_test_connection_does_not_persist_a_row`
- `test_post_integration_first_jira_connect_flips_jirac_mcp_provider_row_enabled_true`
- `test_post_integration_first_github_connect_flips_github_mcp_provider_row_enabled_true`
- `test_integration_role_ADMIN_OWNER_passes_QA_VIEWER_403`
- `test_integration_kind_validation_only_supported_jira_linear_github_slack`

**Implementation:**

- Schemas in `packages/shared/suitest_shared/schemas/integration.py`: `IntegrationCreate(kind, config_json, secrets: dict)`, `IntegrationUpdate`, `IntegrationRead` (omits secrets entirely; has `has_secrets: bool`), `JiraTestConnectionRequest`, `GitHubTestConnectionRequest`.
- Router at `apps/api/src/suitest_api/routers/integrations.py`:
  ```
  @router.post("", response_model=IntegrationRead, status_code=201,
               dependencies=[Depends(require_role({Role.ADMIN, Role.OWNER}))])
  async def create_integration(body: IntegrationCreate, …): ...

  @router.post("/{integration_id}/test", response_model=TestConnectionResult, status_code=200,
               dependencies=[Depends(require_role({Role.ADMIN, Role.OWNER}))])
  async def test_integration(integration_id: str, …): ...

  @router.post("/jira/test-connection", response_model=TestConnectionResult, status_code=200,
               dependencies=[Depends(require_role({Role.ADMIN, Role.OWNER}))])
  async def test_jira_pre_save(body: JiraTestConnectionRequest, …): ...

  @router.post("/github/test-connection", response_model=TestConnectionResult, status_code=200,
               dependencies=[Depends(require_role({Role.ADMIN, Role.OWNER}))])
  async def test_github_pre_save(body: GitHubTestConnectionRequest, …): ...
  ```
- Service `integration_service.py`:
  - `create(...)` — AES-GCM encrypt secrets via `packages/core/crypto.aes_gcm_encrypt`; INSERT row; on first successful Jira/GitHub create, flip the bundled `mcp_providers.enabled=true`.
  - `update(...)` — secret merge: incoming dict's keys overwrite, missing keys retained (so FE doesn't have to know all secret keys).
  - `delete(...)` — soft delete (`deleted_at` if present in `integrations` table; else `status=inactive`).
  - `test(...)` — load adapter via M1d-11 registry, call `adapter.test_connection()`.
- Pre-save test connection uses an ephemeral adapter instantiated with provided creds (not persisted), invokes `test_connection`, discards.
- Audit rows: `integration.created`, `integration.updated`, `integration.deleted`, `integration.tested`, `integration.synced`, `integration.test_connection.jira`, `integration.test_connection.github`.

**Verification:**

- `pytest apps/api/tests/routers/test_integrations_crud.py -q` → green.
- `curl` round-trip: POST creates row, GET never returns secret, PATCH partial-update preserves untouched secret.
- `mypy --strict apps/api packages/core` clean.

**Done when:**

- [ ] All 6 endpoints (`POST/PATCH/DELETE`, `POST /test`, `POST /sync`, `POST /jira|github/test-connection`) shipped.
- [ ] AES-GCM at rest + no secret echo.
- [ ] First-connect flips bundled MCP `enabled=true`.
- [ ] ADMIN/OWNER role-gated.
- [ ] Commit: `feat(api): integration CRUD + test + sync + pre-save test-connection — AES-GCM, no secret echo`.

**Cross-refs:** `docs/API.md §3.x (integrations)` lines 418-444, `docs/DATA_MODEL.md §3.x` (Integration ORM), `packages/core/crypto`.

---

## Task M1d-20 — FE `<SplitGenerateButton>` + `<ManualCreateModal>`

**Goal:** Add a split-button on the Cases list page with "New manual case" (default, enabled) + "Generate from PRD" (`<Gated feature="ai_generation">` → upgrade hint in ZERO) + "Record" / "Import OpenAPI" / "Crawl URL" (all disabled with `<DisabledTooltip reason="Available in M2">`). Clicking Manual opens `<ManualCreateModal>` (name, suite picker, optional first step).

**Out of scope:** Recorder / OpenAPI / Crawler implementations (M2). PRD generation (M3). The full case editor (M1d-21).

**Tests to write** (in `apps/web/src/components/cases/__tests__/SplitGenerateButton.test.tsx` + `ManualCreateModal.test.tsx`):

- `splits_default_action_to_manual_create`
- `dropdown_shows_5_options_manual_record_openapi_crawler_ai`
- `ai_option_in_zero_tier_renders_UpgradeHint_via_Gated`
- `recorder_openapi_crawler_show_DisabledTooltip_M2`
- `manual_modal_opens_on_click_default`
- `manual_modal_validates_name_min_3_chars`
- `manual_modal_suite_picker_required_for_workspaces_with_suites`
- `manual_modal_submits_to_POST_test_cases_then_navigates_to_case_editor`
- `manual_modal_zero_tier_first_step_requires_code_field_when_step_added`
- `manual_modal_close_on_esc_and_overlay_click`

**Implementation:**

- Component `apps/web/src/components/cases/SplitGenerateButton.tsx` — radix `<DropdownMenu>` + primary button. Uses `useCapabilities()` to detect ZERO and wrap AI option.
- Component `apps/web/src/components/cases/ManualCreateModal.tsx` — RHF + Zod (`zCreateTestCase`), shadcn `<Dialog>` + `<Select>` (suite picker, fetched via `useQuery(['suites', projectId])`).
- API client method in `apps/web/src/lib/api-client.ts`: `createTestCase(body): Promise<TestCaseRead>`.
- Wired into `apps/web/src/routes/_app/cases.index.tsx` top toolbar.

**Verification:**

- `pnpm -F web vitest run src/components/cases` → green.
- `pnpm -F web tsc --noEmit` clean.

**Done when:**

- [ ] Split button + modal shipped, AI option `<Gated>`-wrapped, M2 options disabled with tooltip.
- [ ] Manual create POSTs and navigates to `/cases/:id` editor.
- [ ] Commit: `feat(web): split generate button + manual create modal with M2 disabled tooltips`.

**Cross-refs:** `docs/UI_SPEC.md §4` (Cases list toolbar), `Suitest.html` for visual reference, `docs/CAPABILITY_TIERS.md` (Gated behaviour).

---

## Task M1d-21 — FE `<CaseEditor>` route (RHF + Zod + dnd-kit + Monaco lazy)

**Goal:** Implement the full case editor at `/cases/:caseId`: name/description/tags/priority via RHF+Zod, step list via `useFieldArray` + `@dnd-kit/sortable` reorder via grip handle (keyboard-accessible), `step.code` via lazy-loaded `@monaco-editor/react` (Suspense fallback `<TextareaPlaceholder/>`), `Cmd/Ctrl+S` save shortcut, `useBlocker` unsaved-changes guard, `If-Unmodified-Since` 409 conflict toast → "Reload" CTA.

**Out of scope:** Bulk action sticky bar (M1d-22). Defect cards on case detail (M1d-24). "Run now" button (M1d-26).

**Tests to write** (in `apps/web/src/components/cases/__tests__/CaseEditor.test.tsx`):

- `renders_case_metadata_form_with_zod_validation_errors`
- `step_list_renders_steps_in_order_in_suite`
- `drag_grip_handle_reorders_steps_persists_via_PATCH_steps_reorder` (dnd-kit `MouseSensor`)
- `keyboard_arrow_down_with_grip_focused_moves_step_down` (dnd-kit `KeyboardSensor`)
- `monaco_editor_lazy_loads_only_when_step_code_input_focused` — assert initial bundle doesn't include `monaco`.
- `cmd_s_triggers_save_optimistic_PATCH_metadata`
- `cmd_s_unsaved_changes_indicator_shows_dirty_dot`
- `unsaved_changes_guard_blocks_navigation_until_save_or_discard`
- `patch_409_CONCURRENT_MODIFICATION_shows_conflict_toast_with_reload_cta`
- `add_step_appends_with_new_order_in_suite_via_POST_test_cases_id_steps`
- `delete_step_removes_from_field_array_pending_save`
- `monaco_a11y_keyboard_navigation_axe_smoke`

**Implementation:**

- Route file `apps/web/src/routes/_app/cases.$caseId.tsx`:
  ```
  export const Route = createFileRoute('/_app/cases/$caseId')({
    loader: async ({ params }) => fetchTestCase(params.caseId),
    component: CaseEditorPage,
  });
  ```
- Component `apps/web/src/components/cases/CaseEditor.tsx`:
  - RHF `useForm<CaseEditorFormShape>({ resolver: zodResolver(zCaseEditor), defaultValues })`.
  - `useFieldArray({ control, name: "steps" })`.
  - dnd-kit: `<DndContext sensors={[MouseSensor, KeyboardSensor]}><SortableContext items={fields}>…</SortableContext></DndContext>`.
  - Monaco lazy: `const MonacoCodeEditor = lazy(() => import('@/components/cases/MonacoCodeEditor'));` rendered inside `<Suspense fallback={<TextareaPlaceholder/>}>`.
  - Hotkey: `useEffect` registers `keydown` listener for `(e.metaKey||e.ctrlKey) && e.key === 's'` → preventDefault → trigger `onSubmit`.
  - Unsaved guard: TanStack Router `useBlocker({ shouldBlockFn: () => formState.isDirty })`.
  - Optimistic patch: `useMutation` with `onMutate` snapshot, `onError` rollback, `onSettled` invalidate `["test-case", caseId]`. On 409 `CONCURRENT_MODIFICATION`, show sonner toast with "Reload" action that re-fetches.
  - Step `code` field validation: in ZERO tier (from `useCapabilities()`), `zCaseEditor.refine(s => s.code || tier !== "ZERO")` with path = `steps[N].code`.
- New components: `MonacoCodeEditor.tsx` (wraps `@monaco-editor/react`), `TextareaPlaceholder.tsx`, `StepRow.tsx`, `StepReorderHandle.tsx`.
- CI assertion: `pnpm build --analyze` confirms `monaco` chunk is not in initial vendor bundle. Add a Vitest test that imports `vite-bundle-visualizer`'s manifest to assert this.

**Verification:**

- `pnpm -F web vitest run src/components/cases/__tests__/CaseEditor.test.tsx` → green.
- `pnpm -F web tsc --noEmit` clean.
- `pnpm -F web build --analyze` shows Monaco chunk separate.

**Done when:**

- [ ] Full editor with RHF+Zod+dnd-kit+Monaco-lazy+hotkey+unsaved-guard shipped.
- [ ] 409 conflict UX wired.
- [ ] Monaco chunk lazy (bundle-analyze assertion green).
- [ ] axe a11y smoke green on the route.
- [ ] Commit: `feat(web): case editor with RHF/Zod, dnd-kit reorder, lazy Monaco, save hotkey, unsaved guard, 409 conflict toast`.

**Cross-refs:** `docs/UI_SPEC.md §4` (case editor layout), `docs/API.md §47, §200, §205, §62` (`If-Unmodified-Since` + 409).

---

## Task M1d-22 — FE bulk-ops sticky action bar + multi-select + optimistic

**Goal:** Add a multi-select column to Cases list, sticky bottom bar appearing when ≥1 row selected, with actions: Delete, Move to suite, Change priority, Add/Remove tags. Optimistic update + rollback. Calls `POST /test-cases/bulk-update` from M1d-7.

**Out of scope:** Async bulk progress UI. Bulk operations on suites or requirements.

**Tests to write** (in `apps/web/src/components/cases/__tests__/BulkActionBar.test.tsx`):

- `multi_select_checkbox_per_row_and_master_in_header`
- `master_checkbox_toggles_all_visible_rows`
- `sticky_bar_appears_when_at_least_one_selected_disappears_when_zero`
- `bar_shows_selected_count`
- `delete_action_calls_bulk_update_with_action_delete_optimistic_removes_rows`
- `delete_action_rollback_on_500_restores_rows_and_shows_error_toast`
- `move_to_suite_opens_suite_picker_dialog_then_calls_bulk_update_action_move_to_suite_payload_suite_id`
- `change_priority_combobox_calls_bulk_update_action_change_priority`
- `add_tags_chip_input_calls_bulk_update_action_add_tags`
- `remove_tags_chip_input_calls_bulk_update_action_remove_tags`
- `selecting_more_than_100_disables_bar_actions_shows_tooltip_max_100`
- `cmd_a_selects_visible_page_not_all_filtered_results`

**Implementation:**

- Component `apps/web/src/components/cases/BulkActionBar.tsx` — fixed-position `<aside className="fixed bottom-0 left-64 right-0 bg-elev-1 border-t border-border …">`; renders only when `selectedIds.size > 0`.
- Hook `apps/web/src/stores/use-bulk-selection.ts` — Zustand store: `selectedIds: Set<string>`, `add(id)`, `remove(id)`, `toggleVisible(visibleIds)`, `clear()`.
- API client: `bulkUpdateTestCases(body): Promise<BulkUpdateResult>`.
- TanStack Query optimistic update: `useMutation` with `onMutate` snapshotting `queryClient.getQueryData(["test-cases", filters])`, applies action client-side, returns rollback fn.

**Verification:**

- `pnpm -F web vitest run src/components/cases/__tests__/BulkActionBar.test.tsx` → green.

**Done when:**

- [ ] Multi-select column + sticky bar shipped.
- [ ] 5 actions wired with optimistic + rollback.
- [ ] 100-id cap enforced client-side.
- [ ] Commit: `feat(web): bulk-ops sticky action bar with multi-select + optimistic delete/move/priority/tags`.

**Cross-refs:** `docs/UI_SPEC.md §4` (bulk-ops bar), `docs/API.md §3.1` line 208.

---

## Task M1d-23 — FE `<Toaster>` + `undoToast` wired to all soft-deletes

**Goal:** Mount `sonner` `<Toaster richColors closeButton position="bottom-right" duration={8000}>` in `__root.tsx`. Add a `undoToast(label, onUndo)` helper showing "Deleted X. Undo" with 8s window. Wire into case/suite/project/requirement delete mutations so user clicks Undo → invokes `/restore` and refetches.

**Out of scope:** Toasts for non-delete operations (those use plain `toast.success`). Bulk-delete undo (only single-item undo).

**Tests to write** (in `apps/web/src/components/shared/__tests__/undoToast.test.tsx`):

- `toaster_mounted_at_root`
- `undo_toast_renders_label_and_undo_button`
- `undo_toast_auto_dismisses_after_8_seconds`
- `undo_click_invokes_restore_callback_and_dismisses`
- `delete_case_undo_calls_POST_test_cases_id_restore_and_refetches_list`
- `delete_suite_undo_calls_POST_suites_id_restore`
- `delete_project_undo_calls_POST_projects_id_restore`
- `delete_requirement_undo_calls_POST_requirements_id_restore`
- `undo_toast_stacks_max_3_visible_at_once`

**Implementation:**

- `apps/web/src/components/shared/undoToast.tsx`:
  ```
  export function undoToast(message: string, onUndo: () => Promise<void> | void) {
    const id = toast(message, {
      action: { label: "Undo", onClick: async () => { await onUndo(); toast.dismiss(id); } },
      duration: 8000, closeButton: true,
    });
    return id;
  }
  ```
- Wire into delete mutations in: `apps/web/src/routes/_app/cases.index.tsx`, `suites/`, `projects/`, `requirements/`.

**Verification:**

- `pnpm -F web vitest run src/components/shared/__tests__` → green.

**Done when:**

- [ ] `<Toaster>` mounted; `undoToast` helper shipped.
- [ ] Wired to four delete mutations.
- [ ] Commit: `feat(web): undo toast helper + sonner Toaster mounted, wired to case/suite/project/requirement deletes`.

**Cross-refs:** `docs/UI_SPEC.md §1` (shell), `Suitest.html` for toast visual.

---

## Task M1d-24 — FE Defect cards interactive (status, assignee, severity, sync, filters)

**Goal:** Make `/defects` cards interactive: status combobox, assignee user-picker, severity edit, "Sync to tracker" button, filter chips (status/severity/auto-filed/manual), and an "auto-filed only" toggle.

**Out of scope:** Defect detail page redesign. Comment thread. AI explainability ("Why was this auto-filed?" — M3).

**Tests to write** (in `apps/web/src/components/defects/__tests__/DefectCard.test.tsx`):

- `card_renders_publicId_title_status_severity_assignee_kind`
- `status_combobox_transitions_OPEN_to_IN_PROGRESS_calls_PATCH_defects`
- `status_combobox_RESOLVED_to_CLOSED_works_OPEN_to_CLOSED_disabled_per_state_machine`
- `assignee_user_picker_calls_PATCH_with_assignee_user_id`
- `severity_edit_inline_calls_PATCH`
- `sync_to_tracker_button_disabled_when_no_external_tracker_configured`
- `sync_to_tracker_button_calls_POST_defects_id_sync_external_shows_loading_then_toast`
- `filter_chip_auto_filed_only_filters_list_to_created_by_system`
- `filter_chip_severity_S0_only_filters`
- `filter_chip_status_OPEN_only_filters`
- `defect_created_WS_event_appends_new_card_top_of_list`

**Implementation:**

- Component `apps/web/src/components/defects/DefectCard.tsx`.
- Hooks: `usePatchDefect(defectId)`, `useSyncDefectExternal(defectId)`.
- Filter store in `apps/web/src/stores/use-defects-filter.ts` (Zustand).
- WS subscribe: `useWorkspaceStream` handler for `defect.created` / `defect.updated` triggers `queryClient.invalidateQueries(['defects'])`.

**Verification:**

- `pnpm -F web vitest run src/components/defects` → green.

**Done when:**

- [ ] Cards interactive (status/assignee/severity/sync).
- [ ] Filter chips + auto-filed-only toggle.
- [ ] WS-driven list updates.
- [ ] Commit: `feat(web): defect cards interactive with status/assignee/severity/sync + filter chips`.

**Cross-refs:** `docs/UI_SPEC.md §6` (Defects page), `Suitest.html`.

---

## Task M1d-25 — FE Integrations page (Connect / Configure / Disconnect + OAuth callback route)

**Goal:** Implement `/integrations` with one card per supported kind (Jira, Linear, GitHub, Slack). Each card shows status pill, Connect/Configure/Disconnect buttons. Connect modal collects creds, calls pre-save `/integrations/jira|github/test-connection` first, then POSTs. Disconnect confirms via dialog. "Set as default tracker" / "default for notifications" toggles per kind. Route `/integrations/oauth-callback` exists (reserved for M5 OAuth flows; in M1d it just renders an empty placeholder + back link).

**Out of scope:** OAuth implementations (PAT/Webhook only for M1d). Integration history view. Webhook secret regeneration.

**Tests to write** (in `apps/web/src/components/integrations/__tests__/IntegrationsPage.test.tsx`):

- `renders_four_cards_jira_linear_github_slack_in_canonical_order`
- `jira_card_connect_modal_collects_url_email_token_auth_type_and_pre_validates_via_test_connection_endpoint`
- `jira_connect_test_connection_failure_shows_inline_error_does_not_persist`
- `jira_connect_success_POSTs_to_integrations_then_card_shows_connected_pill`
- `slack_connect_modal_collects_webhook_url_and_confirms_intrusive_test_message_dialog_before_test`
- `slack_disconnect_confirms_via_dialog_then_DELETEs_integration`
- `github_connect_modal_collects_app_id_installation_id_private_key_pem`
- `linear_connect_modal_collects_team_id_pat`
- `set_as_default_tracker_toggle_PATCHes_integration_default_for_defects_true_disables_others`
- `oauth_callback_route_renders_placeholder_with_back_link`
- `card_status_error_shows_red_pill_with_last_error_hover_tooltip`

**Implementation:**

- Routes:
  - `apps/web/src/routes/_app/integrations.tsx` (extends M1b shell).
  - `apps/web/src/routes/_app/integrations.oauth-callback.tsx` (new — placeholder).
- Components in `apps/web/src/components/integrations/`: `IntegrationsPage.tsx`, `JiraConnectModal.tsx`, `LinearConnectModal.tsx`, `GitHubConnectModal.tsx`, `SlackConnectModal.tsx`, `IntegrationCard.tsx`, `DisconnectConfirmDialog.tsx`.
- Use shadcn `<Dialog>` + RHF + Zod per modal.
- For Slack, intrusive `test_connection` confirm dialog: "This will post a 'Suitest connection test' message to the configured channel. Continue?".

**Verification:**

- `pnpm -F web vitest run src/components/integrations` → green.

**Done when:**

- [ ] Page + 4 connect modals + disconnect dialog shipped.
- [ ] Pre-save test-connection wired for Jira + GitHub.
- [ ] Slack intrusive confirm.
- [ ] Default tracker / notifications toggles.
- [ ] OAuth callback placeholder route.
- [ ] Commit: `feat(web): integrations page connect/configure/disconnect with pre-save test + OAuth callback placeholder`.

**Cross-refs:** `docs/UI_SPEC.md §8` (Integrations page), `docs/API.md §3.x` lines 418-444.

---

## Task M1d-26 — FE "Run now" button on case detail + gating-suite picker on Dashboard

**Goal:** Two FE additions: (1) "Run now" button in top-right action toolbar of `/cases/:caseId` (per `docs/UI_SPEC.md §3.2` line 282) → calls `POST /test-cases/:id/run` from M1d-8 → success toast with deep-link to `/runs/:id`. (2) Dashboard gating-suite picker dialog: choose a project's gating suite (uses `PATCH /projects/:id` from M1d-5), success toast.

**Out of scope:** Run cancel / re-run buttons (those are M1d-33 rewire). Multi-case run selection from list (M2). Run scheduling.

**Tests to write** (in `apps/web/src/components/cases/__tests__/RunNowButton.test.tsx` + `dashboard/GatingSuitePickerDialog.test.tsx`):

- `run_now_button_disabled_when_case_has_zero_steps`
- `run_now_button_disabled_when_zero_tier_case_has_step_without_code_shows_tooltip_validation_will_fail`
- `run_now_click_calls_POST_test_cases_id_run_navigates_to_runs_id_on_success`
- `run_now_400_STEPS_REQUIRE_CODE_IN_ZERO_LLM_renders_capability_banner_with_stepIndex`
- `gating_suite_picker_opens_from_dashboard_card_button_set_gating_suite`
- `gating_suite_picker_lists_active_suites_in_project`
- `gating_suite_picker_save_PATCHes_project_gating_suite_id`
- `gating_suite_picker_success_toast_deep_links_to_project_settings_route_when_provided`

**Implementation:**

- Component `apps/web/src/components/cases/RunNowButton.tsx` — top-right action toolbar slot in case editor route.
- Component `apps/web/src/components/dashboard/GatingSuitePickerDialog.tsx`.
- API: `runTestCaseNow(caseId): Promise<AdHocRunResponse>`, `setProjectGatingSuite(projectId, suiteId)`.
- Toast: `toast.success("Run queued.", { action: { label: "View", onClick: () => router.navigate({ to: '/runs/$runId', params: { runId } }) } })`.

**Verification:**

- `pnpm -F web vitest run src/components/cases/__tests__/RunNowButton.test.tsx src/components/dashboard` → green.

**Done when:**

- [ ] "Run now" button on case editor route works + handles validation errors.
- [ ] Gating-suite picker dialog on dashboard works.
- [ ] Both with deep-link success toasts.
- [ ] Commit: `feat(web): "Run now" button + gating-suite picker dialog with deep-link toasts`.

**Cross-refs:** `docs/UI_SPEC.md §3.2` line 282 (case detail action toolbar), `docs/API.md §3.1` line 204.

---

## Task M1d-27 — Admin audit log UI (virtualized table) + `GET /audit-logs` filters

**Goal:** Implement `/settings/audit` admin-only route with a virtualized table (TanStack Virtual) listing audit rows with cursor pagination and filters: action glob, resource type, user, date range. Backend: verify `GET /audit-logs` per `docs/API.md §146-158` already supports `?cursor=&action=&resource_type=&user_id=&from=&to=&limit=50`; add any missing filter (action glob).

**Out of scope:** Audit log export. Audit log retention policy UI. Audit log alerting.

**Tests to write** (backend in `apps/api/tests/routers/test_audit_logs.py`):

- `test_get_audit_logs_cursor_pagination_returns_next_cursor`
- `test_get_audit_logs_action_glob_test_case_star_matches_test_case_created_updated`
- `test_get_audit_logs_resource_type_filter`
- `test_get_audit_logs_user_id_filter`
- `test_get_audit_logs_from_to_date_filter`
- `test_get_audit_logs_role_ADMIN_OWNER_only_QA_VIEWER_403`

**Tests to write** (FE in `apps/web/src/components/admin/__tests__/AuditLogTable.test.tsx`):

- `renders_virtualized_table_50_rows_visible_initial`
- `scroll_to_bottom_loads_next_cursor`
- `action_glob_filter_input_calls_api_with_action_query_param`
- `date_range_picker_filters_from_to`
- `clicking_resource_id_navigates_to_detail_route_if_known`
- `viewer_role_redirected_away_route_guarded`

**Implementation:**

- Backend: Audit router likely exists from M1a (read-only). Verify filter support; add `action` glob if missing (use Postgres `LIKE` with `%` substitution).
- FE component `apps/web/src/components/admin/AuditLogTable.tsx` using `@tanstack/react-virtual`.
- Route `apps/web/src/routes/_app/settings.audit.tsx` with role guard (`loader: () => { if (role !== "ADMIN" && role !== "OWNER") throw redirect({ to: "/" }); }`).

**Verification:**

- `pytest apps/api/tests/routers/test_audit_logs.py -q` → green.
- `pnpm -F web vitest run src/components/admin/__tests__/AuditLogTable.test.tsx` → green.

**Done when:**

- [ ] `GET /audit-logs` filter support verified/added.
- [ ] FE virtualized table + cursor pagination + filters.
- [ ] ADMIN/OWNER route guard.
- [ ] Commit: `feat(api,web): admin audit log UI with virtualized table + cursor pagination + action-glob filter`.

**Cross-refs:** `docs/API.md §146-158`, `docs/UI_SPEC.md §9` (settings).

---

## Task M1d-28 — Workspace settings (General / Members / Danger Zone)

**Goal:** Implement `/settings/workspace` with three tabs: General (name, slug, `strict_zero_validation` toggle, `mcp_routing_overrides` JSON editor — Monaco lazy), Members (invite by email, remove member, change role), Danger Zone (slug-type-to-confirm delete via `DELETE /workspaces/:id` OWNER-only).

**Out of scope:** SSO config (M5+). API key management (M2). Workspace transfer.

**Tests to write** (backend in `apps/api/tests/routers/test_workspaces_settings.py`):

- `test_patch_workspace_strict_zero_validation_toggles`
- `test_patch_workspace_mcp_routing_overrides_validates_JSON_schema_targetKind_keys`
- `test_post_workspace_members_invites_by_email_with_role`
- `test_delete_workspace_members_role_ADMIN_OWNER_only_QA_403`
- `test_delete_workspace_requires_slug_in_body_for_confirmation_400_SLUG_MISMATCH_otherwise`
- `test_delete_workspace_role_OWNER_only_ADMIN_403`
- `test_delete_workspace_soft_deletes_marks_inactive_does_not_hard_delete_immediately`

**Tests to write** (FE in `apps/web/src/components/admin/__tests__/WorkspaceSettings.test.tsx`):

- `general_tab_renders_name_slug_strict_zero_toggle_mcp_routing_overrides_editor`
- `members_tab_invite_email_picks_role_calls_POST_members`
- `members_tab_remove_member_confirms_dialog`
- `danger_zone_delete_button_red_outlined_opens_confirm_modal`
- `danger_zone_confirm_modal_requires_user_to_type_workspace_slug_exact_match`
- `danger_zone_delete_only_visible_to_owner`

**Implementation:**

- Backend: extend `apps/api/src/suitest_api/routers/workspaces.py` (or add): `PATCH /workspaces/:id` (settings), `POST /workspaces/:id/members`, `DELETE /workspaces/:id/members/:user_id`, `DELETE /workspaces/:id` with body `{slug_confirm}`.
- FE: `apps/web/src/routes/_app/settings.workspace.tsx` + components `GeneralSettings.tsx`, `MembersSettings.tsx`, `DangerZone.tsx`.

**Verification:**

- `pytest apps/api/tests/routers/test_workspaces_settings.py -q` → green.
- `pnpm -F web vitest run src/components/admin/__tests__/WorkspaceSettings.test.tsx` → green.

**Done when:**

- [ ] 3 tabs shipped; role guards correct.
- [ ] Type-slug-to-confirm delete.
- [ ] `strict_zero_validation` toggle persists.
- [ ] Commit: `feat(api,web): workspace settings — General/Members/Danger Zone with slug-typed-confirm delete`.

**Cross-refs:** `docs/UI_SPEC.md §9`, `docs/DATA_MODEL.md §3.2` (Workspace).

---

## Task M1d-29 — E2E `test_auto_defect_e2e.py` (gates M1d milestone)

**Goal:** Full chain E2E: testcontainers Postgres + Redis + MinIO seed → POST `/test-cases` with row-count-assertion step → POST `/test-cases/:id/run` → runner picks up → step fails on assertion → auto-filer categorizes REGRESSION → defect inserted with `created_by='system'` → mock Jira receives `jira_issue_create` invocation → mock Slack receives webhook POST. This is the milestone gate.

**Out of scope:** Real Jira / Slack integration (mocked). FE-level E2E (M1d-30 Playwright covers that).

**Tests to write** (in `apps/api/tests/e2e/test_auto_defect_e2e.py`):

- `test_full_auto_defect_chain_pg_seed_run_fails_categorize_REGRESSION_persists_mock_jira_called_mock_slack_called` — single big integration test, ~3 min runtime allowed.
- `test_dedup_second_failure_for_same_run_case_does_not_double_file`
- `test_jira_failure_does_not_break_slack_post`
- `test_workspace_strict_zero_FALSE_disables_validator_step_without_code_still_executes_and_fails_at_runtime`

**Implementation:**

- Fixture stack at `apps/api/tests/e2e/conftest.py`:
  ```
  @pytest.fixture(scope="session")
  async def pg_container(): yield from testcontainers.PostgresContainer(...)
  @pytest.fixture(scope="session")
  async def redis_container(): ...
  @pytest.fixture(scope="session")
  async def minio_container(): ...
  @pytest.fixture
  def mock_jira_mcp(monkeypatch):  # patches packages/mcp/client to short-circuit jirac-mcp tool calls
      calls = []
      async def fake_call_tool(self, name, args, **kwargs):
          calls.append((name, args))
          if name == "jira_issue_create":
              return McpToolResult(ok=True, stdout='{"key":"PROJ-123","id":"100","self":"…"}', duration_ms=10)
          ...
      monkeypatch.setattr(McpSession, "call_tool", fake_call_tool)
      return calls
  @pytest.fixture
  def mock_slack_webhook(respx_mock): respx_mock.post("https://hooks.slack.com/services/T/X/Y").mock(return_value=httpx.Response(200))
  ```
- Test body seeds a workspace + project + suite + Jira integration (mocked) + Slack integration; creates a case with a `postgres-mcp` `db.assert_row_count` step expecting 0 rows but actual is 5; calls `POST /test-cases/:id/run`; waits for run to fail (poll `GET /runs/:id` or subscribe WS); asserts defect row, mock_jira_mcp calls, mock_slack_webhook calls.

**Verification:**

- `uv run pytest apps/api/tests/e2e/test_auto_defect_e2e.py -q --maxfail=1` → green.
- Total CI time < 5 min.

**Done when:**

- [ ] E2E test passes end-to-end.
- [ ] Dedup test green.
- [ ] Jira-failure-doesn't-break-slack invariant proven.
- [ ] `strict_zero_validation=False` lenient path covered.
- [ ] Commit: `test(api): e2e auto-defect chain — run fails → categorize → persist → mock Jira+Slack`.

**Cross-refs:** All M1d-1 through M1d-15.

---

## Task M1d-30 — Golden-path Playwright E2E in CI (login → create case → run → result)

**Goal:** Implement `apps/web/e2e/golden-path.spec.ts` (Playwright Test) running against the full docker-compose stack: login → click "New manual case" → fill `<ManualCreateModal>` → land on case editor → add a step using bundled `api-http-mcp` GET against `https://httpbin.org/get` (allowed in test env) → save → click "Run now" → assert WS `run.completed` event surfaces in UI → assert run row shows PASS.

**Out of scope:** Visual regression (M1d-31). Negative path E2E (deferred).

**Tests to write** (in `apps/web/e2e/golden-path.spec.ts`):

- `test_login_and_create_manual_case_then_run_pass` — happy path.
- `test_login_fails_with_bad_credentials_redirects_to_login_with_error` — sanity to prove login flow not bypassed.
- `test_session_expires_redirects_to_login` — short auth TTL in test mode.

**Implementation:**

- Playwright config at `apps/web/playwright.config.ts`: `baseURL` = `http://localhost:5173`, projects `[chromium, firefox]`, retries 1, traceOnFailure.
- `apps/web/e2e/golden-path.spec.ts` — uses `page.getByRole`, `page.getByLabel`, `page.waitForResponse` to wait for `POST /test-cases` etc.
- CI workflow `.github/workflows/m1d-e2e.yml`:
  ```
  name: M1d E2E
  on: [pull_request]
  jobs:
    golden-path:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - run: docker compose up -d
        - run: uv sync && pnpm install
        - run: pnpm -F web playwright install --with-deps chromium
        - run: pnpm -F web playwright test e2e/golden-path.spec.ts
  ```

**Verification:**

- `pnpm -F web playwright test e2e/golden-path.spec.ts` against local stack → green.
- CI workflow runs ≤ 10 min.

**Done when:**

- [ ] Playwright config + golden-path spec landed.
- [ ] CI workflow runs on every PR.
- [ ] Trace+screenshot uploaded on failure.
- [ ] Commit: `test(web): golden-path Playwright E2E — login, create case, run, see result`.

**Cross-refs:** `docs/ROADMAP.md` M1-28.

---

## Task M1d-31 — Visual-regression ≥95% match + loading/empty/error states audit

**Goal:** Set up Percy (or Playwright's built-in `toHaveScreenshot` with `maxDiffPixelRatio: 0.05`) baselines for Cases edit / Defects / Integrations pages vs `Suitest.html` mockup. Add per-screen loading-skeleton + empty-state + error-state components, audited via Vitest snapshot tests.

**Out of scope:** Deletion of `Suitest.html` (Q10 default: keep through M2).

**Tests to write** (in `apps/web/e2e/visual-regression.spec.ts`):

- `cases_edit_matches_Suitest_html_baseline_95_percent`
- `defects_page_matches_baseline_95_percent`
- `integrations_page_matches_baseline_95_percent`
- `dashboard_matches_baseline_95_percent`

**Tests to write** (Vitest in `apps/web/src/components/**/*.test.tsx`):

- One `renders_loading_skeleton_when_query_isLoading` per data-fetching screen.
- One `renders_empty_state_with_cta_when_data_is_empty` per list screen.
- One `renders_error_state_with_retry_when_query_isError` per data-fetching screen.

**Implementation:**

- Add Playwright `toHaveScreenshot` calls in the new visual-regression spec.
- Baselines stored at `apps/web/e2e/__screenshots__/`.
- New components `EmptyState.tsx`, `LoadingSkeleton.tsx`, `ErrorState.tsx` under `apps/web/src/components/shared/`.
- Per-screen wiring: `cases.index.tsx`, `defects.tsx`, `integrations.tsx`, `dashboard.tsx`, etc.
- CI uploads diff artifacts on fail.

**Verification:**

- `pnpm -F web playwright test e2e/visual-regression.spec.ts` → green.
- `pnpm -F web vitest run` → all loading/empty/error tests green.

**Done when:**

- [ ] Baselines ≥95% match on 4 screens.
- [ ] Loading/empty/error states added everywhere.
- [ ] CI artifacts on diff fail.
- [ ] Commit: `feat(web): visual-regression baselines + loading/empty/error states audited`.

**Cross-refs:** `docs/ROADMAP.md` M1-29, M1-30; `CLAUDE.md §1` (Suitest.html note).

---

## Task M1d-32 — Tag `v0.5.0-m1d` + CHANGELOG entry (release task)

**Goal:** After every M1d-1..M1d-33 box is green, write CHANGELOG.md entry summarizing M1d scope; tag intermediate `v0.5.0-m1c+1` if any hotfixes landed since M1c; final tag `v0.5.0-m1d`; push tag.

**Out of scope:** Public announcement. Demo video. Blog post (separate marketing PR).

**Tests to write:** none (release task). Verify via:

- `git tag -l "v0.5.0-m1d"` returns the tag.
- `git log --oneline v0.4.0-m1c..v0.5.0-m1d | wc -l` ≥ 33.
- CHANGELOG.md entry exists with the same boxes-green list as the spec acceptance criteria.

**Implementation:**

- Update `CHANGELOG.md` with section:
  ```
  ## v0.5.0-m1d — 2026-??-?? — ZERO mode closeout

  ### Added
  - Manual TCM writes (#M1-12): POST/PATCH test-cases, …
  - Soft-delete + restore for test-cases, suites, projects, requirements (#M1-13)
  - Bulk-update endpoint with 100-id cap (#M1-15)
  - Rule-based defect auto-filer (REGRESSION/FLAKE/INFRA/SPEC_DRIFT/MANUAL_TRIAGE) (#M1-21)
  - Integration adapters: Jira (via bundled jirac-mcp), Linear (httpx), GitHub (via bundled github-mcp-server), Slack (webhook) (#M1-22, #M1-27)
  - GitHub / GitLab / Jira webhook receivers with gating-suite trigger (#M1-27b/c/d)
  - Workspace settings: General / Members / Danger Zone
  - Admin audit log UI
  - Bundled MCP binaries: `jirac-mcp@jira-mcp-v2.0.1` + `github-mcp-server@v1.1.2`
  - Image size +45 MiB (acceptable per DEPLOYMENT.md §15)

  ### Migration
  - `workspaces.strict_zero_validation` (default TRUE)
  - `workspaces.mcp_routing_overrides`, `suites.mcp_routing_overrides`
  - `suites.deleted_at` + `ix_suites_project_active`
  - `test_cases.order_in_suite`
  - `projects.gating_suite_id`
  - `mcp_providers.{command_pin, image_pin, version_pin, git_ref}` (all `VARCHAR(200/100)`)
  - `mcp_providers.workspace_id` → nullable (bundled/global providers carry `NULL`)
  - `mcp_providers.enabled BOOLEAN NOT NULL DEFAULT 'true'`
  - `uq_defects_auto_dedup` partial unique index
  - Seed rows: `jirac-mcp`, `github-mcp` (both `workspace_id=NULL`, `enabled=false`)

  ### Notes
  - First Jira/GitHub connect flips bundled MCP `enabled=true`.
  - Run dedup uses Redis SETNX (no Postgres partial idx).
  - All public ids via `generate_public_id` helper — no new global sequences.
  ```
- `git tag -a v0.5.0-m1d -m "M1d ZERO closeout"`.
- `git push origin v0.5.0-m1d`.

**Done when:**

- [ ] CHANGELOG.md updated.
- [ ] Tag `v0.5.0-m1d` created and pushed.
- [ ] Commit: `chore: tag v0.5.0-m1d — M1d DoD complete`.

**Cross-refs:** `docs/ROADMAP.md` M1 DoD.

---

## Task M1d-33 — UI rewire of stale "ships in M1c" tooltips

**Goal:** Remove pre-M1c placeholder `<DisabledTooltip>` and wire the now-shipped endpoints: `POST /runs/:id/cancel` (M1c task 15-16) for Cancel button on `apps/web/src/routes/_app/runs.tsx:398`, `POST /runs/:id/rerun` for Re-run button at `:404`, and the "ships in M1c" tooltip on `defects.tsx:90`.

**Out of scope:** Run scheduling buttons (M2). Bulk run cancel.

**Tests to write** (in `apps/web/src/routes/_app/__tests__/runs-cancel-rerun.test.tsx`):

- `cancel_button_clickable_not_disabled`
- `cancel_button_calls_POST_runs_id_cancel_then_invalidates_run_query`
- `cancel_button_403_role_VIEWER_renders_capability_banner`
- `rerun_button_calls_POST_runs_id_rerun_navigates_to_new_run_id_on_success`
- `defects_page_no_longer_shows_ships_in_M1c_tooltip`

**Implementation:**

- Edit `apps/web/src/routes/_app/runs.tsx`:
  - Replace `<DisabledTooltip reason="Cancel ships in M1c">` wrapper on line 398 with direct `<Button onClick={onCancel}>` calling `useMutation(() => cancelRun(runId))`.
  - Replace `"Re-run ships in M1c"` on line 404 with `<Button onClick={onRerun}>` calling `useMutation(() => rerunRun(runId))` → navigate to returned `runId`.
- Edit `apps/web/src/routes/_app/defects.tsx` line 90: remove stale tooltip.
- API client additions: `cancelRun(runId)`, `rerunRun(runId): Promise<{ runId: string }>`.

**Verification:**

- `pnpm -F web vitest run src/routes/_app/__tests__/runs-cancel-rerun.test.tsx` → green.

**Done when:**

- [ ] Stale tooltips removed from `runs.tsx:398,404` and `defects.tsx:90`.
- [ ] Cancel + Re-run wired to shipped M1c endpoints.
- [ ] Commit: `feat(web): rewire cancel/re-run buttons + remove stale ships-in-M1c tooltips`.

**Cross-refs:** M1c plan-04 Task 15-16 (run cancel/rerun endpoints).

---

## Dependency graph

```
M1d-1 ──┬─ M1d-2 ─┬─ M1d-3 ─┬─ M1d-20 ─ M1d-21 ─ M1d-22 ─ M1d-29
        │         │         │
        │         │         └─ M1d-7 ─ ...
        │         └─ M1d-4 ─ M1d-5 ─ M1d-6
        ├─ M1d-8
        ├─ M1d-9 ─ M1d-10 ─ M1d-29
        ├─ M1d-11 ─┬─ M1d-12 ─┐
        │          ├─ M1d-13  │
        │          ├─ M1d-14 ─┤
        │          └─ M1d-15  │
        ├─ M1d-16 ─┬─ M1d-17  │
        │          └─ M1d-18  │
        ├─ M1d-19 ─────────────┘
        └─ M1d-27, M1d-28, M1d-33
              ↓
           M1d-30 ─ M1d-31 ─ M1d-32 (tag)
```

**Parallel-safe clusters** (after M1d-1 lands):

- Group A (backend writes): M1d-2 → M1d-3 → M1d-7 (depends on M1d-2)
- Group B (suite/project/req): M1d-4 || M1d-5 || M1d-6 (each parallel after M1d-1)
- Group C (run shortcut): M1d-8 (depends only on M1d-1 + M1c RunService)
- Group D (defects): M1d-9 → M1d-10 (depends on M1d-9 + M1d-1's partial idx)
- Group E (integrations): M1d-11 → {M1d-12, M1d-13, M1d-14, M1d-15} parallel (caveat: M1d-12 + M1d-14 each modify Dockerfile → merge sequentially even if review-parallel)
- Group F (webhooks): M1d-16 → {M1d-17, M1d-18} parallel
- Group G (integration CRUD): M1d-19 (depends on M1d-11)
- Group H (FE): M1d-20 (after M1d-2), M1d-21 (after M1d-2..3), M1d-22 (after M1d-7 + M1d-21), M1d-23 (after any soft-delete), M1d-24 (after M1d-9), M1d-25 (after M1d-12..15 + M1d-19), M1d-26 (after M1d-8), M1d-27 (after M1a audit + verify), M1d-28
- M1d-33 (UI rewire): independent — parallel with any FE PR.
- M1d-29 (E2E): final gate before tag, depends on M1d-1..M1d-19.
- M1d-30 + M1d-31: after FE PRs land.
- M1d-32: last — tag.

---

## Self-review checklist (run before submitting each PR)

- [ ] **TDD evidence:** failing test commit predates impl commit (or co-commit shows red→green in CI log).
- [ ] **mypy --strict** clean for touched packages (`apps/api`, `apps/runner`, `packages/db`, `packages/shared`, `packages/mcp`, `packages/core`).
- [ ] **ruff check + ruff format --check** clean.
- [ ] **pnpm -F web tsc --noEmit** clean; **vitest** green.
- [ ] **No `as any`** in new TS code.
- [ ] **No `Any`** in new Python code (use `TypedDict`/`Protocol`/generics).
- [ ] **Audit log per mutation** wired through `packages/db/audit.py::write_audit` in same transaction.
- [ ] **WS event** emitted per write to `workspace:<wsId>` (or `run:<runId>` for runner events).
- [ ] **Role gate** declared on every new route (`Depends(require_role({…}))`).
- [ ] **Cross-workspace requests return 404, not 403** (workspace invariant from M1a).
- [ ] **Error envelope** matches `docs/API.md §3` table for any new error code.
- [ ] **`If-Unmodified-Since`** honored on any new `PATCH` that mutates `updated_at`.
- [ ] **Public ids** via `generate_public_id(prefix, workspace_id)` — no string concat / no global sequences.
- [ ] **Secrets** through `packages/core/crypto.aes_gcm_encrypt` only — never plaintext in DB, never echoed in response.
- [ ] **OTel span** on every external call (`mcp.invoke`, `integration.http`, `webhook.recv`).
- [ ] **Conventional commit** message; **no Co-Authored-By trailer**.
- [ ] **One acceptance criterion = one PR**; PR description references the M1d-N task box.

---

## Security checklist (M1d-specific)

- [ ] **AES-GCM at rest** for all `Integration.secrets_encrypted` and webhook secrets. Master key from `SUITEST_ENCRYPTION_KEY` env, 32-byte base64, validated at app startup.
- [ ] **No secret echo** in `IntegrationRead` or any `*Read` response. Verify via grep for `secrets_encrypted` in response serializers.
- [ ] **HMAC constant-time compare** (`hmac.compare_digest`) on `POST /webhooks/github` (sha256) and `POST /webhooks/gitlab` (X-Gitlab-Token). Never plain string `==`.
- [ ] **Per-workspace webhook secret lookup** — one tenant's secret cannot replay another's; secret is derived from the integration row matched via path / installation id, not from a global env.
- [ ] **GitHub App private key PEM** stays in env (`SUITEST_GITHUB_APP_PRIVATE_KEY_PEM`) or AES-GCM at rest; never logged; passed to `_sign_app_jwt` only.
- [ ] **MCP env injection** uses `pool.acquire(provider, env_overrides=...)` so secrets enter the subprocess env once and don't persist on disk (`jirac-mcp` does not write `~/.config/jira/config.toml`).
- [ ] **OAuth callback CSRF** — state token in signed cookie (already covered by FastAPI-Users + `itsdangerous`). Even though M1d ships PAT/App only, the OAuth callback route exists; reject mismatched state.
- [ ] **Bulk endpoint workspace isolation** — pre-validate every id belongs to current workspace; on mismatch, 403 with offending ids; **never partial-apply** across workspaces.
- [ ] **Role gating** correct: case writes QA+, project + integration ADMIN+, workspace danger zone OWNER-only, audit log read ADMIN+.
- [ ] **Cross-workspace reads** return 404 (not 403) so existence isn't leaked.
- [ ] **MCP secret env injection** — `JiraAdapter` + `GitHubAdapter` test cases assert the secret value is passed via `env_overrides` dict and NOT via `provider.env` (which would persist in the DB row).
- [ ] **No plaintext secret in audit metadata** — audit `metadata` only carries hashes or last-4 / `redacted: true`.

---

## Performance checklist (M1d-specific)

- [ ] **Monaco editor lazy-loaded** in `<CaseEditor>` via `lazy()` + `<Suspense>`. Bundle-analyze assertion: `monaco` chunk not in initial vendor bundle.
- [ ] **Optimistic FE updates** for bulk-delete + delete + status edit + reorder; rollback on error; invalidate on settled.
- [ ] **Single-transaction bulk** at `POST /test-cases/bulk-update` — one DB transaction span in OTel.
- [ ] **Single-transaction cascade soft-delete** on suite + project — verified via OTel span.
- [ ] **Atomic step replace + reorder** uses single transaction + `UPDATE … FROM unnest(...)`; no N+1.
- [ ] **Atomic step append** uses `SELECT MAX(order_in_suite) FOR UPDATE` to avoid race.
- [ ] **Webhook dedup** via Redis `SETNX` 60s TTL — sub-ms check; no Postgres round-trip on dup.
- [ ] **MCP session pool reused** — Jira / GitHub adapters use `packages/mcp/client` connection pool from M1c; no per-call subprocess spawn.
- [ ] **`github-mcp-server` env `GITHUB_TOOLSETS=issues`** trims surface so MCP `list_tools` payload stays small.
- [ ] **Virtualized table** at `/settings/audit` (TanStack Virtual) — no DOM blow-up on 10k rows.
- [ ] **`ix_suites_project_active` partial idx** used by suite list queries — verified via `EXPLAIN`.
- [ ] **`uq_defects_auto_dedup` partial idx** prevents double-file under runner retry — verified via concurrency test in M1d-10.
- [ ] **Slack notification ARQ job** runs outside the request path — auto-filer enqueues, doesn't block.
- [ ] **`installation_token` cached 50 min** — re-mint avoided on every GitHub adapter call.
- [ ] **`httpx.AsyncClient` shared** across Linear + GitHub + Slack adapters via app lifespan DI — single TLS pool.

---

## Hand-off to M2

After M1d ships, M2 (generators + MCP expansion) starts from a substantially de-risked base:

- **`packages/mcp` + bundled providers** already cover Jira, GitHub, Slack-via-webhook, Postgres, Playwright, HTTP. M2 adds the **Recorder** (`playwright-mcp.browser.start_recording` flow), **OpenAPI generator** (`api-http-mcp` + spec-driven step synth), **URL crawler** (`browser.crawl_*` if added), **Custom MCP registration UI** (workspace-level config), **MCP tool browser** (read tool catalog UI), **mixed-MCP test E2E demo** (DB seed → API call → browser assert).
- **`IssueTrackerAdapter` Protocol** is generic — M2 can register Tacticlaunch `mcp-linear` if it's matured to ≥1.1 with self-host support, replacing the M1d httpx LinearAdapter without breaking the integration contract.
- **`DefectAutoFiler`** is rule-based today; M3 swaps `DefectCategorizer` for an LLM-backed implementation (via LiteLLM in `packages/agent`) — the dataclass `CategorizedDefect` + the runner hook stay unchanged.
- **Public-id helper** (`generate_public_id`) absorbs new prefixes (`RUN-`, `STEP-`, `LINK-`) without new migrations.
- **Webhook receivers** + Redis SETNX dedup are reusable for additional triggers (cron from M2/M5).
- **`Suitest.html`** still around through M2 visual completion; after generator UIs hit ≥95% match, it can finally be deleted (Q10).
- **CHANGELOG / tagging discipline** in M1d-32 sets the cadence for M2 (`v0.6.0-m2` after acceptance criteria green).

M2 entry tasks (out of scope here, but unblocked):

- M2-1 Recorder generator (Playwright Codegen via MCP) — reuses `playwright-mcp` + browser session.
- M2-2 OpenAPI generator — parses spec, emits steps targeting `api-http-mcp`.
- M2-3 URL crawler — drives `browser.navigate` + DOM analysis, suggests assertions.
- M2-6..11 Custom MCP registration UI + tool browser + mixed-MCP demo.
- M2-12 Code export (`?target=playwright|cypress|selenium`).
- M2 Linear-MCP re-evaluation.

---

## Appendix A — Per-task PR description template

Use this template for every M1d PR. Copy, fill, submit. Reviewers expect every field.

```
## Closes
M1d-N — <one-sentence acceptance criterion>

## Roadmap
ROADMAP.md acceptance: #M1-N

## Summary
<2-3 sentences>

## Schema / Data model
- New columns: …
- New indexes: …
- Migration revision: …
- Rollback risk: LOW|MED|HIGH (why)

## API
- New endpoints: …
- Error envelopes: <table of (code, status, when)>
- Role gate: <Role names>
- Tier gate: ZERO (always for M1d)
- Audit actions: <list>
- WS events emitted: <list of (event, room)>

## Tests
- Backend pytest files: …
- Frontend vitest files: …
- E2E spec (if applicable): …
- Coverage threshold met (no regressions)

## Manual verification
1. <curl invocations>
2. <UI flow>
3. <expected WS / audit / artifact>

## Security
- Secrets: stored via packages/core/crypto AES-GCM
- HMAC: hmac.compare_digest used (where applicable)
- Cross-workspace: 404 (not 403)
- Role gate: <Role>

## Performance
- Single-tx for multi-row writes (where applicable)
- Optimistic FE update + rollback (where applicable)
- Monaco / heavy chunks lazy-loaded (where applicable)

## Out of scope
<bullets>

## Cross-refs
- docs/API.md §…
- docs/DATA_MODEL.md §…
- docs/UI_SPEC.md §…
- docs/MCP_PLUGINS.md §… (if relevant)
```

---

## Appendix B — Shared test fixtures (new this milestone)

Reusable fixtures live under `apps/api/tests/conftest.py` (or `apps/runner/tests/conftest.py`) and may be referenced by name from any task's test files.

### B.1 `seeded_workspace`

```
@pytest.fixture
async def seeded_workspace(db_session) -> WorkspaceContext:
    """Returns a context object with workspace_id, project_id, suite_id, owner_user_id,
    admin_user_id, qa_user_id, viewer_user_id. Used by every routes test."""
```

### B.2 `mock_mcp_session`

```
@pytest.fixture
def mock_mcp_session(monkeypatch):
    """Patches packages/mcp/client.McpSession.call_tool so each test can register
    (tool_name → fake_response) pairs without spawning real subprocesses.

    Usage:
        mock_mcp_session.register("jira_issue_create", {"key": "PROJ-1", "id": "1"})
        # … test code that triggers JiraAdapter.create_external_issue …
        assert mock_mcp_session.calls == [("jira_issue_create", {…args…})]
    """
```

### B.3 `respx_jira_cassette` / `respx_linear_cassette` / `respx_github_cassette` / `respx_slack_cassette`

```
@pytest.fixture
def respx_linear_cassette(respx_mock, request):
    """Loads YAML cassette named after the test, replays as respx routes.
    Cassettes under apps/api/tests/integrations/cassettes/linear/<test_name>.yaml."""
```

### B.4 `arq_test_pool`

```
@pytest.fixture
async def arq_test_pool():
    """In-memory ARQ pool that executes jobs synchronously for assertion convenience.
    Use only in unit tests; full E2E uses real Redis testcontainer."""
```

### B.5 `fake_redis`

```
@pytest.fixture
def fake_redis():
    """In-memory replacement for redis.asyncio.Redis exposing .publish/.set/.get/.delete.
    Captures published messages in fake_redis.published[channel]."""
```

### B.6 `fake_ws_publisher`

```
@pytest.fixture
def fake_ws_publisher():
    """Captures all WS publishes to .events: list[tuple[str, dict]] (room, payload).
    Inject into services via dependency override."""
```

### B.7 `bundled_jirac_mcp_provider` / `bundled_github_mcp_provider`

```
@pytest.fixture
def bundled_jirac_mcp_provider(seeded_workspace) -> McpProviderConfig:
    """Returns the seeded jirac-mcp provider config with command_pin / enabled=true."""
```

### B.8 `aes_gcm_key_test`

```
@pytest.fixture(autouse=True)
def aes_gcm_key_test(monkeypatch):
    """Sets SUITEST_ENCRYPTION_KEY to a fixed 32-byte base64 test value so
    integration crypto tests are deterministic."""
```

---

## Appendix C — Frontend testing patterns (vitest)

### C.1 `renderWithProviders`

```
// apps/web/src/test/render.tsx
export function renderWithProviders(ui: ReactNode, opts?: { tier?: Tier; role?: Role }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([...]);
  return render(
    <QueryClientProvider client={queryClient}>
      <CapabilitiesProvider value={{ tier: opts?.tier ?? "ZERO" }}>
        <AuthProvider value={{ role: opts?.role ?? "QA" }}>
          <RouterProvider router={router}>{ui}</RouterProvider>
        </AuthProvider>
      </CapabilitiesProvider>
    </QueryClientProvider>,
  );
}
```

### C.2 `mockApi`

```
// apps/web/src/test/mock-api.ts — light typed wrapper over msw
export const mockApi = {
  testCases: {
    list: (body: TestCaseRead[]) => http.get("/api/v1/test-cases", () => HttpResponse.json({ items: body })),
    create: (body: TestCaseRead) => http.post("/api/v1/test-cases", async () => HttpResponse.json(body, { status: 201 })),
    patch: (id: string, body: TestCaseRead) => http.patch(`/api/v1/test-cases/${id}`, async () => HttpResponse.json(body)),
    delete: (id: string) => http.delete(`/api/v1/test-cases/${id}`, () => new HttpResponse(null, { status: 204 })),
    run: (id: string, body: AdHocRunResponse) => http.post(`/api/v1/test-cases/${id}/run`, async () => HttpResponse.json(body, { status: 201 })),
  },
  // … defects, integrations, projects, suites, requirements, workspaces, runs …
};
```

### C.3 `MockWs`

```
// apps/web/src/test/mock-ws.ts — reused from M1c plan-04 Task 19.3
// Adds: mockWs.publish({ event: "case.created", data: { … } });
```

### C.4 Visual regression baseline naming

Baselines live at `apps/web/e2e/__screenshots__/<spec-name>/<browser>/<test-id>.png`. Updating: `pnpm -F web playwright test --update-snapshots` (review diff in PR carefully). Threshold per spec via `await expect(page).toHaveScreenshot({ maxDiffPixelRatio: 0.05 })`.

---

## Appendix D — Docker bundling cheat sheet (for PR-12 + PR-14)

### D.1 Jira MCP (`jirac-mcp@jira-mcp-v2.0.1`)

Stage to add to `infra/docker/Dockerfile.api` (and identically to `infra/docker/Dockerfile.runner`):

```dockerfile
FROM alpine:3.19 AS jira-mcp-downloader
ARG TARGETARCH
ARG JIRA_MCP_VERSION=jira-mcp-v2.0.1
RUN apk add --no-cache curl tar
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) ARCH=x86_64 ;; \
      arm64) ARCH=aarch64 ;; \
      *) echo "Unsupported TARGETARCH=$TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fL --retry 3 \
      "https://github.com/mulhamna/jira-commands/releases/download/${JIRA_MCP_VERSION}/jirac-mcp-linux-${ARCH}.tar.gz" \
      | tar -xz -C /tmp; \
    install -m0755 "/tmp/jirac-mcp-linux-${ARCH}" /usr/local/bin/jirac-mcp; \
    /usr/local/bin/jirac-mcp --version
```

Smoke step at the end of the final stage:

```dockerfile
RUN /usr/local/bin/jirac-mcp --version
```

### D.2 GitHub MCP (`github-mcp-server@v1.1.2`)

```dockerfile
FROM alpine:3.19 AS gh-mcp-downloader
ARG TARGETARCH
ARG GH_MCP_VERSION=v1.1.2
RUN apk add --no-cache curl tar
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) ARCH=x86_64 ;; \
      arm64) ARCH=arm64 ;; \
      *) echo "Unsupported TARGETARCH=$TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fL --retry 3 \
      "https://github.com/github/github-mcp-server/releases/download/${GH_MCP_VERSION}/github-mcp-server_Linux_${ARCH}.tar.gz" \
      | tar -xz -C /tmp; \
    install -m0755 "/tmp/github-mcp-server" /usr/local/bin/github-mcp-server; \
    /usr/local/bin/github-mcp-server --version
```

### D.3 Final stage `COPY` lines

```dockerfile
FROM python:3.12-slim AS final
# … existing python deps + suitest packages …
COPY --from=jira-mcp-downloader /usr/local/bin/jirac-mcp /usr/local/bin/jirac-mcp
COPY --from=gh-mcp-downloader   /usr/local/bin/github-mcp-server /usr/local/bin/github-mcp-server
RUN /usr/local/bin/jirac-mcp --version && /usr/local/bin/github-mcp-server --version
```

### D.4 Multi-arch build cmd (CI)

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f infra/docker/Dockerfile.api \
  -t suitest/api:m1d-rc \
  --push .
```

### D.5 Image-size guardrails

- `python:3.12-slim` base: ~144 MiB.
- After M1d bundle add: ~189 MiB (≈+45 MiB total).
- CI assertion: `docker images suitest/api:m1d-rc --format "{{.Size}}"` parsed; fail PR if ≥ +60 MiB delta (gives 15 MiB slack).

### D.6 SBOM regeneration

`docs/DEPLOYMENT.md §15` SBOM table must list both binaries with version + checksum. PR-12 + PR-14 each update one row.

---

## Appendix E — Adapter contract reference (canonical Jira / GitHub tool names)

### E.1 `jirac-mcp@jira-mcp-v2.0.1` tools used by M1d

| Adapter method | MCP tool | Args (minimal) | Notes |
|---|---|---|---|
| `test_connection` | `jira_api_request` | `{method: "GET", path: "/rest/api/3/myself"}` | whoami check |
| `create_external_issue` | `jira_issue_create` | `{project_key, summary, description, issue_type, priority?, assignee?, labels?}` | returns `{key, id, self}` |
| `update_external_issue` | `jira_issue_update` | `{issue_key, fields:{...}}` | partial update |
| `transition_status` step 1 | `jira_issue_transitions_list` | `{issue_key}` | returns `[{id, name, to:{name}}]` |
| `transition_status` step 2 | `jira_issue_transition` | `{issue_key, transition_id, confirm: true}` | destructive op requires `confirm:true` |
| (optional) lookup | `jira_issue_view` | `{issue_key}` | round-trip after create |
| (optional) comment | `jira_comment_add` | `{issue_key, body}` | future use |
| (optional) link | `jira_issue_link_create` | `{inward_issue, outward_issue, link_type}` | future use |
| (optional) raw | `jira_api_request` | `{method, path, body?}` | escape hatch |

### E.2 `github-mcp-server@v1.1.2` tools used by M1d (with `GITHUB_TOOLSETS=issues`)

| Adapter method | MCP tool | Args (minimal) | Notes |
|---|---|---|---|
| `test_connection` | `list_issues` | `{owner, repo, state: "open", per_page: 1}` | cheap ping |
| `create_external_issue` | `issue_write` | `{action: "create", owner, repo, title, body, labels:[…]}` | returns `{number, html_url, …}` |
| `update_external_issue` | `issue_write` | `{action: "update", owner, repo, issue_number, …}` | partial update |
| `add_comment` | `add_issue_comment` | `{owner, repo, issue_number, body}` | future use |
| `label_write` | `label_write` | `{action: "create"\|"update"\|"delete", owner, repo, name, …}` | severity:* labels pre-create |
| `search` | `search_issues` | `{q: "is:issue suitest …"}` | sync-back lookups |

### E.3 `transition_status` pick algorithm (Jira)

```python
_DEFECT_TO_JIRA_TARGET = {
    DefectStatus.IN_PROGRESS: ("In Progress",),
    DefectStatus.RESOLVED: ("Done", "Resolved"),
    DefectStatus.CLOSED: ("Closed",),
    DefectStatus.WONT_FIX: ("Won't Do", "Wontfix"),
    DefectStatus.OPEN: ("To Do", "Open", "Reopen"),
}

def _pick_transition(self, transitions: list[dict], target: DefectStatus) -> str:
    candidates = _DEFECT_TO_JIRA_TARGET[target]
    for t in transitions:
        if t["to"]["name"] in candidates:
            return t["id"]
    raise IntegrationUpstreamError("jira",
        f"No transition to any of {candidates} from current status")
```

---

## Appendix F — Audit action canonical names

Every M1d write writes an audit row. Use these exact `action` strings (no hyphens, all snake_case, namespaced):

| Action | Resource type | Emitted by |
|---|---|---|
| `test_case.created` | `test_case` | M1d-2 |
| `test_case.metadata_updated` | `test_case` | M1d-2 |
| `test_case.steps_replaced` | `test_case` | M1d-2 |
| `test_case.step_appended` | `test_case` | M1d-2 |
| `test_case.steps_reordered` | `test_case` | M1d-2 |
| `test_case.duplicated` | `test_case` | M1d-2 |
| `test_case.soft_deleted` | `test_case` | M1d-3 |
| `test_case.restored` | `test_case` | M1d-3 |
| `test_case.bulk_deleted` | `test_case` | M1d-7 (per id) |
| `test_case.bulk_moved` | `test_case` | M1d-7 |
| `test_case.bulk_priority_changed` | `test_case` | M1d-7 |
| `test_case.bulk_tags_added` | `test_case` | M1d-7 |
| `test_case.bulk_tags_removed` | `test_case` | M1d-7 |
| `test_case.run_now` | `test_case` | M1d-8 |
| `suite.created` | `suite` | M1d-4 |
| `suite.metadata_updated` | `suite` | M1d-4 |
| `suite.case_order_reordered` | `suite` | M1d-4 |
| `suite.soft_deleted_with_cascade` | `suite` | M1d-4 |
| `suite.restored` | `suite` | M1d-4 |
| `project.created` | `project` | M1d-5 |
| `project.updated` | `project` | M1d-5 |
| `project.gating_suite_changed` | `project` | M1d-5 |
| `project.soft_deleted_with_cascade` | `project` | M1d-5 |
| `requirement.created` | `requirement` | M1d-6 |
| `requirement.updated` | `requirement` | M1d-6 |
| `requirement.soft_deleted` | `requirement` | M1d-6 |
| `requirement.link_created` | `requirement_link` | M1d-6 |
| `requirement.link_deleted` | `requirement_link` | M1d-6 |
| `defect.manual_created` | `defect` | M1d-9 |
| `defect.updated` | `defect` | M1d-9 |
| `defect.status_synced_to_external` | `defect` | M1d-9 |
| `defect.status_synced_from_jira` | `defect` | M1d-18 |
| `defect.auto_filed` | `defect` | M1d-10 (metadata: kind, severity, run_id) |
| `integration.created` | `integration` | M1d-19 |
| `integration.updated` | `integration` | M1d-19 |
| `integration.deleted` | `integration` | M1d-19 |
| `integration.tested` | `integration` | M1d-19 |
| `integration.synced` | `integration` | M1d-19 |
| `integration.test_connection.jira` | `integration` | M1d-19 (pre-save, no resource_id) |
| `integration.test_connection.github` | `integration` | M1d-19 (pre-save, no resource_id) |
| `webhook.github.received` | `webhook` | M1d-16 |
| `webhook.gitlab.received` | `webhook` | M1d-17 |
| `webhook.jira.received` | `webhook` | M1d-18 |
| `workspace.settings_updated` | `workspace` | M1d-28 |
| `workspace.member_invited` | `workspace_member` | M1d-28 |
| `workspace.member_removed` | `workspace_member` | M1d-28 |
| `workspace.soft_deleted` | `workspace` | M1d-28 |

**Convention:** the `metadata` JSON column always carries at minimum `{"by_role": "<role>", "workspace_slug": "<slug>"}` for filterability + downstream analytics.

---

## Appendix G — WS event canonical names

New events emitted in M1d, room is always `workspace:<wsId>` unless noted.

| Event | Payload shape | Emitted by |
|---|---|---|
| `case.created` | `{caseId, publicId, suiteId, by}` | M1d-2 |
| `case.updated` | `{caseId, publicId, fields:[…]}` | M1d-2 |
| `case.steps.replaced` | `{caseId, stepCount}` | M1d-2 |
| `case.deleted` | `{caseId, publicId}` | M1d-3 |
| `case.restored` | `{caseId, publicId}` | M1d-3 |
| `suite.created` | `{suiteId, projectId, name}` | M1d-4 |
| `suite.case_order.reordered` | `{suiteId, caseIds:[…]}` | M1d-4 |
| `suite.soft_deleted` | `{suiteId, cascadedCaseIds:[…]}` | M1d-4 |
| `project.gating_suite_changed` | `{projectId, suiteId}` | M1d-5 |
| `requirement.created` | `{requirementId, publicId}` | M1d-6 |
| `requirement.linked` | `{requirementId, caseId}` | M1d-6 |
| `defect.created` | `{defectId, publicId, kind, severity, createdBy}` | M1d-9 or M1d-10 |
| `defect.updated` | `{defectId, status, severity, assigneeUserId}` | M1d-9, M1d-18 |
| `integration.created` | `{integrationId, kind}` | M1d-19 |
| `integration.error` | `{integrationId, kind, lastError, lastErrorAt}` | M1d-12..15, M1d-19 |

Each event publishes a JSON line: `{"event": "<name>", "data": {…}}`. FE subscribers use `useWorkspaceStream((e) => { if (e.event === "case.created") refetch(); })`.

---

## Appendix H — Error code matrix introduced in M1d

| Code | Status | When | Details fields |
|---|---|---|---|
| `STEPS_REQUIRE_CODE_IN_ZERO_LLM` | 400 | Step lacks `code` in ZERO with `strict_zero_validation=true` | `stepIndex`, `caseId` |
| `MCP_PROVIDER_NOT_REGISTERED` | 404 | Step references unknown provider name | `name` |
| `CONCURRENT_MODIFICATION` | 409 | `If-Unmodified-Since` predates `updated_at` | `resourceType`, `id`, `serverUpdatedAt` |
| `CROSS_WORKSPACE_LINK` | 400 | Req↔case link spans workspaces | `requirementWorkspaceId`, `caseWorkspaceId` |
| `BULK_LIMIT_EXCEEDED` | 400 | bulk-update with >100 ids | `received`, `max` |
| `CROSS_WORKSPACE_BULK` | 403 | bulk-update ids mix workspaces | `offendingIds: list[str]` |
| `CONFIRM_CASCADE_REQUIRED` | 409 | delete suite/project without `confirmCascade=true` | `childCount`, `resourceType` |
| `CROSS_PROJECT_GATING_SUITE` | 400 | set `project.gating_suite_id` to a suite in another project | `suiteProjectId`, `projectId` |
| `DUPLICATE_PROJECT_SLUG` | 409 | slug already exists in workspace after retry | `slug` |
| `SLUG_MISMATCH` | 400 | workspace danger-zone delete payload slug doesn't match | `expected`, `received` |
| `INVALID_STATUS_TRANSITION` | 400 | defect status flow violation | `from`, `to`, `allowed` |
| `NO_DEFAULT_TRACKER` | 404 | `sync-external` with no default tracker | `kindsAvailable: list[str]` |
| `INTEGRATION_UPSTREAM_ERROR` | 502 | adapter upstream call failed | `provider`, `upstreamMessage` |

These are the **only** new codes M1d may introduce. If any task tempts you to add another, surface it as an open question for product review first.

---

## Appendix I — Coverage / quality targets

- **Backend pytest coverage:** ≥ 80% line on each new module (`apps/api/src/suitest_api/services/*`, `apps/api/src/suitest_api/integrations/*`, `apps/api/src/suitest_api/routers/*`). Enforce via `pytest --cov=apps/api/src --cov-fail-under=80`.
- **Frontend vitest coverage:** ≥ 75% line on `apps/web/src/components/cases`, `apps/web/src/components/defects`, `apps/web/src/components/integrations`, `apps/web/src/components/admin`. Enforce via `vitest run --coverage`.
- **mypy --strict** clean across `apps/api`, `apps/runner`, `packages/db`, `packages/shared`, `packages/mcp`, `packages/core`.
- **ruff** + `ruff format --check` clean.
- **TypeScript** `tsc --noEmit` clean (no `as any`, no `// @ts-expect-error` without comment).
- **Playwright** golden-path E2E + visual-regression E2E green on Chromium + Firefox in CI.
- **`docker images suitest/api:m1d-rc`** size ≤ 220 MiB on `linux/arm64`.

---

## Appendix J — Documentation deliverables map

Per CLAUDE §2.1 / §2.3, every code change must reach the right doc. Map of doc files M1d touches:

| Doc | M1d tasks that update it |
|---|---|
| `docs/DATA_MODEL.md §3.x / §11` | M1d-1 (column additions verified against Wave 1 audit) |
| `docs/API.md §3.x` | M1d-2..M1d-9, M1d-16..M1d-19, M1d-27, M1d-28 (any new endpoint or error code) |
| `docs/UI_SPEC.md §3, §4, §6, §8, §9` | M1d-20..M1d-28, M1d-31 |
| `docs/MCP_PLUGINS.md §3 (bundled table), §5.3 (schema persistence)` | M1d-12, M1d-14 |
| `docs/DEPLOYMENT.md §15 (air-gap bundle)` | M1d-12, M1d-14 (binary list + sizes + SBOM) |
| `docs/CAPABILITY_TIERS.md` | No changes expected (M1d is ZERO-only). Verify `<Gated feature="ai_generation">` row still says `<UpgradeHint>` in ZERO. |
| `docs/AUTONOMY.md` | No changes expected (no autonomy gates in M1d). |
| `docs/ROADMAP.md` | M1d-32 (move M1 acceptance boxes to checked) |
| `CHANGELOG.md` | M1d-32 |
| `docs/superpowers/plans/2026-05-26-plan-05-m1d-tcm-writes.md` | Marked SUPERSEDED by this plan (separately, Wave 4) |

---

## Appendix K — Runbook for the implementer agent (subagent-driven-development)

If you're a subagent picking up one of these tasks, follow this protocol:

1. **Read the task in full** (don't skim). Open every file in `Cross-refs` section.
2. **Verify Prerequisites** at the top of this plan for your task in particular.
3. **Branch** `feat/m1d-<task-num>-<short>` from `main`. Never branch from another in-flight feature branch.
4. **Write the failing tests first** in the file paths listed under "Tests to write". Commit them with message `test(m1d-<N>): failing tests for <area>` so the red→green progression is reviewable.
5. **Implement** per the bullet-level signatures in "Implementation". Commit incrementally — one logical chunk per commit.
6. **Verify** per the "Verification" section. Run the exact commands listed.
7. **Tick "Done when"** boxes only when each is genuinely true. No premature checks.
8. **Self-review checklist** (§ "Self-review checklist") + **Security checklist** + **Performance checklist** before opening PR.
9. **Open PR** using the Appendix A template.
10. **Cross-refs in PR description** must match this plan's "Cross-refs" — reviewer will spot omissions.
11. **CI must be green** before requesting review. Don't drop work-in-progress reviews on people.
12. **Squash-merge** with the conventional-commit message proposed under "Commit:".
13. **Tick the box** in `docs/ROADMAP.md` for the M1-N acceptance line your PR closes (if applicable).

If you hit ambiguity:

- First check `docs/superpowers/specs/2026-05-30-m1d-manual-tcm-writes.md` § "Open questions" — maybe it's already resolved or has a default.
- Then check this plan's § "Open spec questions still requiring product confirmation" — adopt the proposed default unless told otherwise.
- If still stuck → comment on the PR draft, tag product. **Do not invent fields, endpoints, or error codes.**

---

## Appendix L — Roll-back / contingency plan

If a critical bug is found post-merge:

- **Backend code regression:** revert the offending commit on `main` + open a follow-up PR with a fix. Don't `git push --force`.
- **Schema regression:** Alembic `downgrade -1` is supported and tested in M1d-1's round-trip test. Downgrade individual revisions if needed. Since each migration is single-purpose, blast radius is bounded.
- **Bundled MCP binary breaks self-host upgrades:** the `command_pin` column lets users override to a known-good version via workspace settings (`mcp_routing_overrides.command_pin_override`). For nuclear escape hatch, set `SUITEST_JIRA_MODE=httpx` / `SUITEST_GITHUB_MODE=httpx` env vars (M2 ships httpx fallbacks; M1d does not, but the env hook is reserved).
- **Auto-defect floods a tracker (categorizer overzealous):** workspace setting `auto_defect_enabled=false` short-circuits `DefectAutoFiler.file_for_failed_step` (already tested in M1d-10). Operators can flip without a deploy.
- **Webhook receiver becomes a DOS surface:** Redis SETNX dedup is the first line. If saturated, set `SUITEST_WEBHOOK_REQUIRE_AUTH=true` to reject any unsigned request (already default behavior; no flag needed).
- **`jirac-mcp` upstream pulls v2.0.1 release:** the binary is cached in our image layer; no immediate impact. M2 mirrors all bundled binaries to our own release artifacts to be self-sufficient.

---

_End of plan 05b — M1d — Manual TCM writes + Rule-based Defects + MCP-native Integrations._
