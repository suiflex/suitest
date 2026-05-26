# M1a — ZERO Backend Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement full SQLAlchemy data model from DATA_MODEL.md, repository + service layers, capability resolver with real env reading and `/capabilities` JSON contract, AES-GCM crypto helper, audit log infrastructure, and all read-only GET endpoints serving seeded data. ZERO tier deployment can be browsed end-to-end by an authenticated user.

**Architecture:** Repository pattern over SQLAlchemy 2 async sessions. FastAPI dependency injection wires `Depends(get_db_session)` → service → repository. Capability tier resolved once at startup, cached in app state, exposed via `/capabilities`. Audit log written via SQLAlchemy event listener on every mutation (not used in this plan since we're read-only, but infrastructure in place). AES-GCM via `cryptography` lib for any secrets-bound table.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, asyncpg, cuid2, cryptography (AES-GCM), pgvector, structlog, OpenTelemetry instrumentation, slowapi (rate limit), pytest-asyncio, testcontainers-python, factory-boy or polyfactory.

---

## How to use this plan

1. Read the **whole** plan once before touching code. Each task assumes earlier tasks compiled and committed.
2. Drive each task TDD-first — write the failing test described in the task, watch it fail, then implement.
3. One task = one conventional commit. Sub-tasks each get their own commit (e.g. `feat(db): add projects + suites models`).
4. Never skip the "verify with `uv run …`" lines — they are the contract for that task being "done".
5. M1a is **read-only** at the HTTP edge; do not add `POST`/`PATCH`/`DELETE` handlers in this plan even if a model exists for them (writes live in plan M1d).
6. Capability gating exists but is **not strictly enforced** for read endpoints — `/capabilities` MUST still return the correct shape per CAPABILITY_TIERS.md.

---

## Conventions referenced throughout

- File paths are **absolute from repo root** (`apps/api/...`, `packages/db/...`).
- All async — every DB call returns awaitable; every route is `async def`.
- Pydantic v2 models always set `model_config = ConfigDict(from_attributes=True, populate_by_name=True, str_strip_whitespace=True)`.
- SQLAlchemy 2 style: `Mapped[...]` + `mapped_column(...)`. No legacy `Column` declarations.
- Tests: `pytest-asyncio` strict mode, `testcontainers-python` for ephemeral Postgres+pgvector, factory-boy or polyfactory for fixtures.
- Conventional commits: `feat(<scope>): …`, `fix(<scope>): …`, `chore(<scope>): …`, `test(<scope>): …`.
- Trailing rule for **every** commit message: `Closes #M1-<n>` referencing the roadmap acceptance criterion when relevant.

---

## Task 1 — Crypto helper

**Path:** `packages/core/suitest_core/crypto.py`
**Tests:** `packages/core/tests/test_crypto.py`
**Roadmap reference:** foundational; supports M1-22/M3-2 secrets storage.

### Goal

Provide AES-256-GCM `encrypt(plaintext, aad)` / `decrypt(blob, aad)` helpers plus a Pydantic-friendly `EncryptedBytes` SQLAlchemy type so downstream models (`Integration.secrets_encrypted`, `LLMConfig.api_key_encrypted`, `McpProvider.secrets_json_encrypted`) can declare a column without re-implementing the cipher.

### Steps

- [ ] **1.1** Add `cryptography>=42` to `packages/core/pyproject.toml` `[project.dependencies]`.
- [ ] **1.2** Write failing test `packages/core/tests/test_crypto.py::test_encrypt_decrypt_roundtrip`:
  - sets `SUITEST_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"\\x00"*32).decode()` in `monkeypatch`,
  - calls `encrypt("hello", aad=b"ws_1")`,
  - asserts the returned `bytes` length == `12 + len("hello") + 16` (nonce + ct + GCM tag),
  - asserts `decrypt(blob, aad=b"ws_1") == "hello"`,
  - asserts `decrypt(blob, aad=b"ws_2")` raises `cryptography.exceptions.InvalidTag`.
- [ ] **1.3** Write failing test `test_missing_key_raises`:
  - `monkeypatch.delenv("SUITEST_ENCRYPTION_KEY", raising=False)`,
  - assert `pytest.raises(RuntimeError, match="SUITEST_ENCRYPTION_KEY not set")` when calling `encrypt("x")`.
- [ ] **1.4** Write failing test `test_wrong_key_length_raises`:
  - set env to base64 of 31 bytes,
  - assert `RuntimeError, match="32 bytes"`.
- [ ] **1.5** Write failing test `test_encrypted_bytes_sqlalchemy_type_bind_and_load`:
  - construct an in-memory SQLAlchemy `MetaData` + `Table("t", meta, Column("blob", EncryptedBytes()))`,
  - bind to SQLite (using `aiosqlite`),
  - insert `{"blob": "secret-value"}` via `conn.execute(t.insert())`,
  - select back and assert the **decrypted** string equals `"secret-value"`,
  - also assert the underlying raw bytes ≠ `"secret-value"` (confirm at-rest encryption).
- [ ] **1.6** Implement `packages/core/suitest_core/crypto.py`:
  ```python
  from __future__ import annotations
  import base64
  import os
  from typing import Any

  from cryptography.hazmat.primitives.ciphers.aead import AESGCM
  from sqlalchemy import LargeBinary
  from sqlalchemy.types import TypeDecorator


  _MISSING = "SUITEST_ENCRYPTION_KEY not set (expect 32 bytes base64)."
  _WRONG_LEN = "SUITEST_ENCRYPTION_KEY must decode to 32 bytes."


  def _key() -> bytes:
      raw = os.environ.get("SUITEST_ENCRYPTION_KEY")
      if not raw:
          raise RuntimeError(_MISSING)
      key = base64.urlsafe_b64decode(raw)
      if len(key) != 32:
          raise RuntimeError(_WRONG_LEN)
      return key


  def encrypt(plaintext: str, aad: bytes = b"") -> bytes:
      aes = AESGCM(_key())
      nonce = os.urandom(12)
      ct = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
      return nonce + ct


  def decrypt(blob: bytes, aad: bytes = b"") -> str:
      if not blob:
          raise ValueError("nothing to decrypt")
      aes = AESGCM(_key())
      nonce, ct = blob[:12], blob[12:]
      return aes.decrypt(nonce, ct, aad).decode("utf-8")


  class EncryptedBytes(TypeDecorator[bytes]):
      """SQLAlchemy column that transparently encrypts/decrypts strings.

      Stored on the wire as LargeBinary (AES-GCM `nonce||ct||tag`). The Python
      side reads/writes plain `str`. AAD is intentionally not bound at the type
      level — callers needing AAD should call ``encrypt`` / ``decrypt`` directly.
      """

      impl = LargeBinary
      cache_ok = True

      def process_bind_param(self, value: str | None, dialect: Any) -> bytes | None:
          if value is None:
              return None
          return encrypt(value)

      def process_result_value(self, value: bytes | None, dialect: Any) -> str | None:
          if value is None:
              return None
          return decrypt(value)
  ```
- [ ] **1.7** Run `uv run pytest packages/core/tests/test_crypto.py -q` — must be green.
- [ ] **1.8** Run `uv run ruff check packages/core` + `uv run mypy packages/core` — clean.
- [ ] **1.9** Commit: `feat(core): add AES-GCM crypto helper + EncryptedBytes type`.

### Verify

```bash
uv run pytest packages/core/tests/test_crypto.py -q
uv run mypy packages/core
```

Both must exit 0.

---

## Task 2 — Full data model

Reference: [DATA_MODEL.md](../../DATA_MODEL.md) (source of truth). Every model below comes from there verbatim — do **not** invent columns. Split into one sub-task per logical entity group so each Alembic revision is reviewable. Each sub-task ends with one commit.

### Shared scaffolding (do **before** Task 2a)

- [ ] **2.0.1** Confirm `packages/db/src/suitest_db/models/base.py` from M0 exposes `Base`, `TimestampMixin`, and `cuid()`. If missing, port the snippet from `DATA_MODEL.md §3.1` verbatim.
- [ ] **2.0.2** Confirm `packages/shared/src/suitest_shared/domain/enums.py` exports **all** enums from `DATA_MODEL.md §6`: `Role, CaseSource, Priority, CaseStatus, RunStatus, RunTrigger, StepOutcome, ArtifactKind, Severity, DefectStatus, IntegrationKind, AgentSessionKind, MessageRole, DocumentKind, TargetKind, Tier, AutonomyLevel, DiagnosisKind, McpTransport`. Add any missing enum verbatim.
- [ ] **2.0.3** Confirm Alembic env (`packages/db/alembic/env.py`) imports **every** model module before `target_metadata = Base.metadata` so autogenerate sees all tables. Create a `packages/db/src/suitest_db/models/__init__.py` that imports each module (but does **not** re-export — barrel exports are banned by CLAUDE.md §2.2). Convention: `import suitest_db.models.tenancy  # noqa: F401`.
- [ ] **2.0.4** Add a session-scoped fixture in `packages/db/tests/conftest.py` that boots a `testcontainers.postgres.PostgresContainer("pgvector/pgvector:pg16")`, exposes it via `engine` + `session` fixtures, and runs `CREATE EXTENSION IF NOT EXISTS vector;` on container startup. Migrations are applied via `alembic.command.upgrade(cfg, "head")` inside the fixture (not raw `metadata.create_all`).

### Task 2a — Users, Workspaces, Memberships

**Path:** `packages/db/src/suitest_db/models/tenancy.py`
**Migration:** `packages/db/alembic/versions/<rev>_tenancy.py`
**Tests:** `packages/db/tests/test_tenancy.py`

- [ ] **2a.1** Extend the M0 `workspaces` table (already migrated) with:
  - `region: Mapped[str] = mapped_column(String(32), default="ap-southeast-1")` if not present.
  - `__table_args__ = ()` — `slug` unique is already enforced.
- [ ] **2a.2** Add `User`:
  - cols: `id` (cuid pk), `email` (`String(255)`, unique), `name` (`String(120)`), `avatar_url` (`String(500) | None`), `TimestampMixin`.
- [ ] **2a.3** Add `Membership`:
  - cols: `id`, `workspace_id` (FK `workspaces.id ON DELETE CASCADE`), `user_id` (FK `users.id ON DELETE CASCADE`), `role` (`SAEnum(Role)`, default `Role.QA`), `TimestampMixin`.
  - `__table_args__`: `UniqueConstraint("workspace_id", "user_id", name="uq_memberships_workspace_user")`, `Index("ix_memberships_user_id", "user_id")`.
- [ ] **2a.4** FastAPI-Users (M0) already manages a `users` table — **reconcile**: extend the FastAPI-Users base to inherit from `Base` and add the extra Suitest columns (`name`, `avatar_url`) as additional columns via Alembic. Do **not** create a second `users` table. Add a comment block at the top of `tenancy.py` explaining the integration.
- [ ] **2a.5** Generate migration: `uv run alembic revision --autogenerate -m "add users, memberships; extend workspaces"`. Open the generated file, verify:
  - `op.create_table("users", ...)` includes `email UNIQUE NOT NULL`.
  - `op.create_table("memberships", ...)` has FK cascade rules.
  - `op.create_index("ix_memberships_user_id", ...)`.
  - `op.add_column("workspaces", sa.Column("region", ...))` if not already present from M0.
- [ ] **2a.6** Tests:
  - `test_create_user_unique_email`: insert two `User(email="a@b.c")` rows → second raises `IntegrityError`.
  - `test_membership_cascade_on_workspace_delete`: create ws + user + membership → delete ws → membership row gone, user row remains.
  - `test_membership_unique_per_workspace_user`: duplicate `(workspace_id, user_id)` raises.
- [ ] **2a.7** Run `uv run alembic upgrade head` against the testcontainer Postgres in CI.
- [ ] **2a.8** Commit: `feat(db): add users + memberships, extend workspaces with region`.

### Task 2b — Projects + Suites

**Path:** `packages/db/src/suitest_db/models/project.py`
**Tests:** `packages/db/tests/test_project.py`

- [ ] **2b.1** `Project` model (cols per DATA_MODEL §3.3): `id`, `workspace_id` FK CASCADE, `slug` (`String(64)`), `name` (`String(120)`), `description` (`String(2048) | None`), TimestampMixin. Unique constraint `(workspace_id, slug)`.
- [ ] **2b.2** `Suite` model: `id`, `project_id` FK CASCADE, `name`, `description`, `order` (default 0), TimestampMixin. Index on `project_id`.
- [ ] **2b.3** Alembic revision `add projects + suites`. Verify:
  - FK cascades present on both tables.
  - `uq_projects_workspace_slug` index name correct.
- [ ] **2b.4** Tests:
  - `test_project_unique_slug_per_workspace`: two `Project(workspace_id=w1, slug="x")` → second raises.
  - `test_project_slug_can_repeat_across_workspaces`: same slug in different workspaces OK.
  - `test_suite_cascade_on_project_delete`: delete project → suite row gone.
  - `test_suite_order_default_zero`: insert without order, query, assert `0`.
- [ ] **2b.5** Commit: `feat(db): add projects + suites`.

### Task 2c — TestCase + TestStep + CaseTag

**Path:** `packages/db/src/suitest_db/models/case.py`
**Tests:** `packages/db/tests/test_case.py`

- [ ] **2c.1** `TestCase` (DATA_MODEL §3.4): all columns including `public_id` (`String(32)`, unique), `source` (`SAEnum(CaseSource)`), `status` (`SAEnum(CaseStatus)`, default ACTIVE), `priority`, `owner_id` FK users (nullable), `generated_by`, `generated_from` (JSONB), `estimated_ms`, `deleted_at` (nullable timestamptz).
- [ ] **2c.2** Indexes: `ix_test_cases_suite_status (suite_id, status)`, `ix_test_cases_source (source)`, `ix_test_cases_deleted_at (deleted_at)`.
- [ ] **2c.3** `TestStep` (DATA_MODEL §3.4): `case_id` FK CASCADE, `order` Integer, `action`/`expected` Text NOT NULL, `code` Text nullable, `data` JSONB nullable, `mcp_provider` (`String(64)`, default `"playwright-mcp"`, **NOT NULL**), `target_kind` (`SAEnum(TargetKind)`, default `FE_WEB`, **NOT NULL**).
- [ ] **2c.4** `TestStep.__table_args__`: `UniqueConstraint("case_id", "order")`, `Index("ix_test_steps_mcp_provider", "mcp_provider")`, `Index("ix_test_steps_target_kind", "target_kind")`. **Do NOT create an `executable` column** — comment block referencing DATA_MODEL §3.4 ("computed at read time via domain `TestStep.executable(tier)`").
- [ ] **2c.5** `CaseTag`: `case_id` FK CASCADE, `tag` (`String(64)`). Unique `(case_id, tag)`. Index on `tag`.
- [ ] **2c.6** Alembic revision `add test_cases, test_steps, case_tags`. Verify enum types (`case_source`, `case_status`, `priority`, `target_kind`) created via `op.create_table` referencing existing PG enums; if not yet created in an earlier revision add `sa.Enum(..., name="…", create_type=True)` only on the **first** table that uses it (typical pitfall: autogen generates `create_type=True` twice → Alembic upgrade fails). Inspect carefully.
- [ ] **2c.7** Tests:
  - `test_test_case_minimum_fields`: create ws → project → suite → case with `source=CaseSource.MANUAL` works.
  - `test_test_step_order_unique_per_case`: insert two steps `order=1` for same case → raise.
  - `test_test_step_defaults`: insert step without `mcp_provider` / `target_kind` → query back, assert `playwright-mcp` and `TargetKind.FE_WEB`.
  - `test_case_tag_unique`: two `(case_id, "smoke")` rows → raise.
  - `test_executable_computed_zero_tier`: build a domain `TestStep` with only `action`, `step.executable(Tier.ZERO)` is False; with `code`, True.
  - `test_executable_computed_cloud_tier`: action-only step → `step.executable(Tier.CLOUD)` is True.
  - `test_cascade_delete_case_cascades_steps_tags`.
- [ ] **2c.8** Commit: `feat(db): add test cases, steps, and tags with MCP routing fields`.

### Task 2d — Requirement + RequirementLink

**Path:** `packages/db/src/suitest_db/models/requirement.py`
**Tests:** `packages/db/tests/test_requirement.py`

- [ ] **2d.1** `Requirement` (§3.5): `id`, `project_id` FK CASCADE, `public_id` unique `String(32)`, `title` `String(255)`, `description` Text nullable, `source` `String(255)` nullable, `external_url` `String(500)` nullable, TimestampMixin.
- [ ] **2d.2** `RequirementLink`: `requirement_id` FK CASCADE, `case_id` FK CASCADE, unique `(requirement_id, case_id)`.
- [ ] **2d.3** Alembic revision `add requirements`. Verify.
- [ ] **2d.4** Tests:
  - `test_requirement_link_unique`: two links same `(req, case)` → raise.
  - `test_requirement_link_cascade_delete_via_case`: delete case → link row gone (req survives).
  - `test_requirement_link_cascade_delete_via_requirement`: delete req → link row gone (case survives).
- [ ] **2d.5** Commit: `feat(db): add requirements + traceability links`.

### Task 2e — Run + RunStep + Artifact

**Path:** `packages/db/src/suitest_db/models/run.py`
**Tests:** `packages/db/tests/test_run.py`

- [ ] **2e.1** `Run` (§3.6) — all cols including `tier_at_runtime` (`SAEnum(Tier)`, NOT NULL), `metadata` JSONB (named `metadata_json` in Python with `Column("metadata", JSONB)` because `metadata` clashes with SQLAlchemy's DeclarativeBase attr). Indexes: `(project_id, status)`, `(created_at)`, `(tier_at_runtime)`.
- [ ] **2e.2** `RunStep`: `run_id` FK CASCADE, `case_id` FK (no CASCADE — preserve history), `step_order`, `outcome` (`SAEnum(StepOutcome)`), timestamps, durations, stdout/stderr/error_*. Index `(run_id, outcome)`.
- [ ] **2e.3** `Artifact`: `run_step_id` FK CASCADE, `kind` (`SAEnum(ArtifactKind)`), `url` `String(1024)` (note: `s3://…` or `file://…`), `size_bytes` Integer, `mime_type` `String(120)`, `metadata` JSONB (use Python attr `metadata_json` again). Index on `run_step_id`.
- [ ] **2e.4** Alembic revision `add runs, run_steps, artifacts`. Verify enum names match DATA_MODEL: `run_status`, `run_trigger`, `step_outcome`, `artifact_kind`, `tier`.
- [ ] **2e.5** Tests:
  - `test_run_requires_tier_at_runtime`: omit tier → `IntegrityError` (NOT NULL).
  - `test_run_step_cascade_on_run_delete`: delete run → run_steps gone, but linked `test_cases` survive.
  - `test_artifact_cascade_on_run_step_delete`.
  - `test_artifact_url_accepts_both_schemes`: insert with `s3://...` and `file://...`, both succeed.
- [ ] **2e.6** Commit: `feat(db): add runs, run_steps, and artifacts with tier_at_runtime`.

### Task 2f — Defect + ExternalIssue

**Path:** `packages/db/src/suitest_db/models/defect.py`
**Tests:** `packages/db/tests/test_defect.py`

- [ ] **2f.1** `Defect` (§3.7) — all cols including `agent_diagnosis_kind` (`SAEnum(DiagnosisKind)`, default `MANUAL_TRIAGE`, **NOT NULL**), `agent_confidence` Float nullable, `stack_trace` Text. Indexes: `(workspace_id, status)`, `(severity)`, `(agent_diagnosis_kind)`.
- [ ] **2f.2** `ExternalIssue`: `defect_id` FK CASCADE, `provider` `String(32)`, `external_id` `String(64)`, `external_url` `String(1024)`, `synced_at` server_default `func.now()`. Unique `(provider, external_id)`.
- [ ] **2f.3** Alembic revision `add defects, external_issues`. Enum `diagnosis_kind` newly created.
- [ ] **2f.4** Tests:
  - `test_defect_default_diagnosis_is_manual_triage`.
  - `test_defect_severity_required`: omit → raise.
  - `test_external_issue_unique_provider_pair`: two `(jira, "PROJ-1")` rows → raise.
- [ ] **2f.5** Commit: `feat(db): add defects + external issues with diagnosis_kind`.

### Task 2g — Integration (encrypted secrets)

**Path:** `packages/db/src/suitest_db/models/integration.py`
**Tests:** `packages/db/tests/test_integration.py`

- [ ] **2g.1** `Integration` (§3.8) — `kind` (`SAEnum(IntegrationKind)`), `config` JSONB NOT NULL, **`secrets_encrypted` uses `EncryptedBytes` from Task 1** (nullable), `status` default `"active"`. Index `(workspace_id, kind)`.
- [ ] **2g.2** Alembic revision `add integrations`. Verify enum `integration_kind` has all values listed in §6 (incl. `MCP_API`, `MCP_POSTGRES`, etc.).
- [ ] **2g.3** Tests:
  - `test_integration_kind_jira`: insert with `kind=IntegrationKind.JIRA` works.
  - `test_integration_secrets_roundtrip`: insert with `secrets_encrypted="cred-xyz"`, query back via separate session, assert decrypted value matches and raw bytes ≠ plaintext (read via low-level `connection.execute(text("SELECT secrets_encrypted ..."))`).
  - `test_integration_mcp_kind_values`: parametrise over all `MCP_*` kinds, insert+roundtrip each.
- [ ] **2g.4** Commit: `feat(db): add integrations with AES-GCM-encrypted secrets column`.

### Task 2h — AgentSession + AgentMessage + AgentToolCall

**Path:** `packages/db/src/suitest_db/models/agent.py`
**Tests:** `packages/db/tests/test_agent.py`

- [ ] **2h.1** `AgentSession` (§3.9) — including all reproducibility cols: `provider`, `prompt_version_id` FK `prompt_versions(id)` nullable, `seed`, `temperature` (Float), `cost_usd` (`Numeric(10,4)` nullable), `tokens_in`/`tokens_out`. Indexes: `(workspace_id, kind)`, `(provider)`.
- [ ] **2h.2** `AgentMessage`: `session_id` FK CASCADE, `role` (`SAEnum(MessageRole)`), `content` Text, `metadata` JSONB. Index on `session_id`.
- [ ] **2h.3** `AgentToolCall`: `message_id` FK CASCADE, `tool_name` `String(120)`, `mcp_provider` `String(64) | None`, `input` JSONB NOT NULL, `output` JSONB nullable, `status` `String(32)` default `"running"`, `duration_ms`, `error_msg` Text.
- [ ] **2h.4** Defer `prompt_version_id` FK creation until Task 2k's `prompt_versions` table exists. Strategy: include the **column** as nullable now, add the **FK constraint** in Task 2k's migration (Alembic supports `op.create_foreign_key` later). Document this in a migration comment.
- [ ] **2h.5** Alembic revision `add agent_sessions, messages, tool_calls`.
- [ ] **2h.6** Tests:
  - `test_agent_session_defaults`: insert minimal → `status="active"`, `tokens_in=0`, `tokens_out=0`.
  - `test_agent_tool_call_input_required`: omit `input` → raise.
  - `test_agent_message_cascade_on_session_delete`.
  - `test_agent_tool_call_cascade_on_message_delete`.
- [ ] **2h.7** Commit: `feat(db): add agent sessions, messages, and tool calls`.

### Task 2i — Document + DocumentChunk (pgvector)

**Path:** `packages/db/src/suitest_db/models/document.py`
**Tests:** `packages/db/tests/test_document.py`

- [ ] **2i.1** Confirm `CREATE EXTENSION IF NOT EXISTS vector` runs before this migration (M0 should have included it; if not, prepend `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` here).
- [ ] **2i.2** `Document` (§3.10): `id`, `workspace_id` FK CASCADE, `kind` (`SAEnum(DocumentKind)`), `source` `String(1024)`, `title` `String(255)`, `content_hash` `String(64)`, `indexed_at` nullable, `meta` JSONB. Index `(workspace_id, kind)`.
- [ ] **2i.3** `DocumentChunk`: `document_id` FK CASCADE, `chunk_index` Integer, `content` Text, `embedding` `Vector(None)` (from `pgvector.sqlalchemy`), `metadata` JSONB (Python attr `metadata_json`). Index on `document_id`. **No** HNSW index in this migration (added per-workspace in a later op-level migration — see DATA_MODEL §7.2). Leave a TODO comment.
- [ ] **2i.4** Alembic revision `add documents + chunks`. Verify `Vector(None)` becomes `vector` column without fixed dim.
- [ ] **2i.5** Tests:
  - `test_document_chunk_variable_dim`: insert chunk with `embedding=[0.1]*384`; insert another with `[0.1]*1536` — both succeed (no per-workspace check constraint in M1a yet).
  - `test_document_cascade_to_chunks`.
- [ ] **2i.6** Commit: `feat(db): add documents + chunks with variable-dim pgvector`.

### Task 2j — AuditLog

**Path:** `packages/db/src/suitest_db/models/audit.py`
**Tests:** `packages/db/tests/test_audit.py`

- [ ] **2j.1** `AuditLog` (§3.11): cols as spec, **no** `TimestampMixin` (only `created_at` server_default, append-only). Index `(workspace_id, created_at)`.
- [ ] **2j.2** Alembic revision `add audit_logs`.
- [ ] **2j.3** Tests:
  - `test_audit_log_required_fields`: omit `action`/`resource_type`/`resource_id` → raise.
  - `test_audit_log_metadata_json_optional`: insert without `metadata` → query back, `metadata is None`.
- [ ] **2j.4** Commit: `feat(db): add audit log table`.

### Task 2k — LLMConfig + WorkspaceCapability + McpProvider + GeneratorRun + PromptVersion + EvalRun + CodeExport

These small tables ship together. One migration, one commit (each model lives in its own file).

**Paths:**
- `packages/db/src/suitest_db/models/llm_config.py`
- `packages/db/src/suitest_db/models/workspace_capability.py`
- `packages/db/src/suitest_db/models/mcp_provider.py`
- `packages/db/src/suitest_db/models/generator_run.py`
- `packages/db/src/suitest_db/models/prompt_version.py`
- `packages/db/src/suitest_db/models/eval_run.py`
- `packages/db/src/suitest_db/models/code_export.py`

**Tests:** `packages/db/tests/test_capability_tables.py`

- [ ] **2k.1** `LLMConfig` (§4.1): `workspace_id` FK CASCADE, `provider`, `model`, **`api_key_encrypted` = `EncryptedBytes` nullable**, `config_json` JSONB default `{}`, `is_active` Boolean default `False`, `last_validated_at` nullable. Index `(workspace_id, is_active)`.
- [ ] **2k.2** `WorkspaceCapability` (§4.2): `workspace_id` FK CASCADE **UNIQUE** (one row per workspace), `tier` (`SAEnum(Tier)`), `autonomy_level` (`SAEnum(AutonomyLevel)`, default `MANUAL`), `features_json` JSONB default `{}`, `updated_at`. Index on `tier`.
- [ ] **2k.3** `McpProvider` (§4.3): cols incl. `transport` (`SAEnum(McpTransport)`), **`secrets_json_encrypted` = `EncryptedBytes` nullable**, `is_default_for_target` JSONB default `{}`, `health_status` default `"unknown"`. Index `(workspace_id, kind)`, unique `(workspace_id, name)`.
- [ ] **2k.4** `GeneratorRun` (§4.4): `source` `String(64)`, `input_meta_json` JSONB default `{}`, `output_case_ids_json` JSONB default `[]`, `duration_ms`, `created_at` server_default, `created_by_user_id` FK users.
- [ ] **2k.5** `PromptVersion` (§4.5): `name`, `version`, `content` Text, `hash` (sha256), `created_at`. Unique `(name, version)`, index on `hash`.
- [ ] **2k.6** `EvalRun` (§4.6): cols as spec.
- [ ] **2k.7** `CodeExport` (§4.7): cols as spec.
- [ ] **2k.8** **NOW** add the `agent_sessions.prompt_version_id → prompt_versions.id` FK constraint deferred from Task 2h via `op.create_foreign_key("fk_agent_sessions_prompt_version_id_prompt_versions", ...)` in this same migration.
- [ ] **2k.9** Alembic revision `add llm_config, capability snapshot, mcp providers, generator runs, prompts, eval runs, code exports`.
- [ ] **2k.10** Tests:
  - `test_workspace_capability_one_per_workspace`: insert two rows for same ws → raise.
  - `test_llm_config_api_key_roundtrip` (EncryptedBytes through real PG round-trip).
  - `test_mcp_provider_unique_name_per_workspace`.
  - `test_prompt_version_unique_name_version`.
  - `test_generator_run_default_jsonb_empty`.
  - `test_agent_session_prompt_version_fk`: insert PromptVersion → insert AgentSession with that fk → query joinedload → assert relationship loads.
- [ ] **2k.11** Commit: `feat(db): add LLM config, capability, MCP providers, generator/prompt/eval/code-export tables`.

### Post-Task 2 sanity check (do not commit; just verify)

- [ ] **2.99.1** `uv run alembic upgrade head` on a fresh PG container — must succeed.
- [ ] **2.99.2** `uv run alembic downgrade base` then back to head — must succeed (catches non-reversible migrations).
- [ ] **2.99.3** `uv run pytest packages/db -q` — all green.
- [ ] **2.99.4** `uv run mypy packages/db` — clean.

---

## Task 3 — Repository pattern

**Path:** `packages/db/src/suitest_db/repositories/`
**Tests:** `packages/db/tests/repositories/`

### Goal

Centralise all SQL behind typed async repositories so services never construct queries inline. Generic `AsyncRepository` provides CRUD; per-entity subclasses add domain-specific helpers.

### Steps

- [ ] **3.1** Create `packages/db/src/suitest_db/repositories/base.py`:
  ```python
  from __future__ import annotations
  from typing import Generic, TypeVar, Sequence, Any
  from datetime import datetime, timezone
  from sqlalchemy import select, func, and_
  from sqlalchemy.ext.asyncio import AsyncSession
  from pydantic import BaseModel

  ModelT = TypeVar("ModelT")
  CreateDTO = TypeVar("CreateDTO", bound=BaseModel)
  UpdateDTO = TypeVar("UpdateDTO", bound=BaseModel)


  class AsyncRepository(Generic[ModelT, CreateDTO, UpdateDTO]):
      model: type[ModelT]

      def __init__(self, session: AsyncSession) -> None:
          self.session = session

      async def get_by_id(self, id: str) -> ModelT | None: ...
      async def get_by_public_id(self, public_id: str) -> ModelT | None: ...
      async def list_paginated(
          self,
          *,
          cursor: tuple[datetime, str] | None,
          limit: int = 20,
          filters: dict[str, Any] | None = None,
      ) -> tuple[Sequence[ModelT], tuple[datetime, str] | None]: ...
      async def create(self, dto: CreateDTO) -> ModelT: ...
      async def update(self, id: str, dto: UpdateDTO) -> ModelT | None: ...
      async def soft_delete(self, id: str) -> bool: ...
      async def count(self, filters: dict[str, Any] | None = None) -> int: ...
  ```
  Fill in concrete implementations:
  - `get_by_id`: `await self.session.scalar(select(self.model).where(self.model.id == id))`.
  - `get_by_public_id`: only if model has `public_id` attr (use `getattr(self.model, "public_id", None)`); else raise `AttributeError`.
  - `list_paginated`: cursor = `(created_at, id)` keyset pagination — `WHERE (created_at, id) < (cursor_ts, cursor_id) ORDER BY created_at DESC, id DESC LIMIT limit+1`. Return `(rows[:limit], next_cursor)` where `next_cursor` is None when results < limit+1.
  - `create`: instantiate model from `dto.model_dump(exclude_unset=True)`, `session.add(row)`, `await session.flush()`, return row.
  - `update`: fetch, apply non-None DTO fields, flush.
  - `soft_delete`: only if model has `deleted_at` column — set to `datetime.now(tz=timezone.utc)`. Raise if column absent.
  - `count`: `await self.session.scalar(select(func.count()).select_from(self.model)` plus filters.
- [ ] **3.2** Per-entity repos (each in its own file, e.g. `workspaces.py`, `projects.py`, …). All workspace-scoped repos accept a `workspace_id` either via constructor or per-method param — pick **per-method param** for explicitness. Required:
  - `WorkspaceRepo`: `list_for_user(user_id)`, `get_by_slug(slug)`.
  - `ProjectRepo`: `list_by_workspace(workspace_id, ...)`, `get_by_slug(workspace_id, slug)`.
  - `SuiteRepo`: `list_by_project(project_id, ...)`.
  - `TestCaseRepo`: `list_by_suite_filtered(suite_id, status=None, source=None, priority=None, tag=None, q=None, cursor=None, limit=20)`, `get_steps(case_id)`, `list_with_steps_by_suite(...)` using `selectinload(TestCase.steps)`.
  - `RequirementRepo`: `list_by_project`, `with_links(req_id)`.
  - `RunRepo`: `list_by_project(project_id, status=None, branch=None, env=None, cursor, limit)`, `get_with_summary(run_id)`, `get_steps(run_id)`, `get_artifacts(run_id)`.
  - `DefectRepo`: `list_by_workspace(workspace_id, status=None, severity=None, assignee_id=None, component=None, cursor, limit)`, `timeline(defect_id)` — returns a synthetic list `[creation event] + [audit_log rows for resource_id=defect_id]`.
  - `IntegrationRepo`: `list_by_workspace(workspace_id, kind=None)`.
  - `DocumentRepo`: `list_by_workspace(workspace_id, kind=None, cursor, limit)`.
  - `AuditLogRepo`: `list_by_workspace(workspace_id, cursor, limit)`, `append(action, resource_type, resource_id, before, after, user_id, ip, ua)`.
  - `LLMConfigRepo`: `get_active(workspace_id)`.
  - `WorkspaceCapabilityRepo`: `get(workspace_id)`, `upsert(workspace_id, tier, autonomy, features)`.
  - `McpProviderRepo`: `list_by_workspace(workspace_id)`, `get_by_name(workspace_id, name)`.
- [ ] **3.3** Cursor encoding: cursor wire format is opaque base64 of JSON `{"ts": iso8601, "id": cuid}`. Helper `encode_cursor` / `decode_cursor` in `repositories/cursor.py`. **Test these helpers separately** (`test_cursor_roundtrip`, `test_cursor_malformed_raises`).
- [ ] **3.4** Factory fixtures (`packages/db/tests/factories.py`):
  - Use `polyfactory.factories.SQLAlchemyFactory` (or factory-boy if preferred). Define one factory per repo target.
  - Each factory accepts an async session and provides `await Factory.create(session=session, ...)`.
  - Workspace factory creates a unique slug (`f"ws-{cuid()}"`).
  - TestCase factory generates a public_id of the form `f"TC-{n}"` by calling the seed-only `nextval('test_cases_pubid_seq')` — but only after Task 8 ships. For M1a fixtures, just generate `f"TC-{random.randint(10000, 99999)}"`.
- [ ] **3.5** Tests (one file per repo, mirror structure):
  - Each repo test creates 3 rows via factory, asserts `list_paginated(cursor=None, limit=2)` returns 2 + cursor; calling again with that cursor returns the third row + cursor=None.
  - `TestCaseRepo.list_by_suite_filtered` parametrised across each filter: status, source, priority, tag, free-text `q` (ILIKE on `name`).
  - `RunRepo.get_with_summary` — verify `total_steps`/`passed_steps`/`failed_steps` reflect inserted RunSteps.
  - `DefectRepo.timeline` — insert defect, insert audit_log rows referencing it, assert ordering by created_at ASC.
  - `WorkspaceCapabilityRepo.upsert` — first call inserts, second call updates same row (`workspace_id` unique constraint).
- [ ] **3.6** `uv run pytest packages/db/tests/repositories -q` — all green.
- [ ] **3.7** `uv run mypy packages/db` — clean (note: `AsyncRepository` generic must be parametrised correctly at use sites).
- [ ] **3.8** Commit: `feat(db): add repository pattern with cursor pagination`.

---

## Task 4 — Service layer

**Path:** `apps/api/src/suitest_api/services/`
**Tests:** `apps/api/tests/services/`

### Goal

Business rules live here — routers stay thin. Services depend on repos via constructor injection; FastAPI wires both via `Depends`. All services declare a capability requirement (default `Tier.ANY` for M1a).

### Steps

- [ ] **4.1** Capability enum in `packages/core/suitest_core/capabilities.py` (used both at services and at the `/capabilities` endpoint — Task 5 imports from here):
  ```python
  from enum import Flag, auto
  class TierFlag(Flag):
      ZERO = auto()
      LOCAL = auto()
      CLOUD = auto()
      ANY = ZERO | LOCAL | CLOUD
  ```
  Test: bitwise membership (`Tier.ZERO in TierFlag.ANY` works through translation helper `tier_in(t: Tier, flag: TierFlag)`).
- [ ] **4.2** Decorator `@require_tier(TierFlag.ANY)` in `apps/api/src/suitest_api/deps/tier.py`. For M1a it is a no-op (still parses + records on the wrapped fn) but it MUST be present on every service method so M3 can flip enforcement.
- [ ] **4.3** Multi-tenant scoping — single helper `apps/api/src/suitest_api/deps/scope.py`:
  ```python
  @dataclass
  class TenantContext:
      workspace_id: str
      user_id: str
      role: Role
  ```
  Resolved via `Depends(current_active_user)` + `X-Workspace-Id` header OR path `workspaceId` (header wins; if both present, must match — else 400).
- [ ] **4.4** Per-entity service files. Each holds a class taking `ctx: TenantContext` + relevant repo(s). Required:
  - `WorkspaceService` (list_for_user, get_by_id_for_user) — note: not scoped by `workspace_id`.
  - `ProjectService`
  - `SuiteService`
  - `TestCaseService` — `list(...)` filters MUST `WHERE suites.project.workspace_id = ctx.workspace_id`; `get_by_id_with_steps(case_id)` 404s if case's workspace ≠ ctx.workspace_id.
  - `RequirementService`, `TraceabilityService` (matrix).
  - `RunService`, `RunArtifactSignedUrlService` (placeholder — returns a presigned URL using MinIO SDK; mock in tests).
  - `DefectService`.
  - `IntegrationService` — redacts secrets in response.
  - `DocumentService`.
  - `AnalyticsService` — methods: `kpis(project_id, period)`, `pass_rate(project_id, period)`, `coverage(project_id)`, `flaky(project_id, min_rate=0.2)`, `heatmap(project_id, period)`, `readiness(project_id)`.
  - `CapabilityService` — resolves deployment tier + (optional) workspace overlay. Used by Task 5.
- [ ] **4.5** Flaky rule (M1-26): for each test case in project, fetch outcomes of last 10 runs (most recent N where the case appeared). Compute `variance = stdev(outcome_as_int)` where `PASS=1, FAIL=0, ERROR=0`. Flag as flaky when `variance > 0.2` AND case appeared in ≥3 of the last 10 runs (avoid 1-shot noise). Method returns `[{caseId, publicId, flakeRate, sampleSize}, ...]`. Single SQL query using window functions where possible; fallback to Python aggregation if SQLAlchemy expression too gnarly — comment which path is taken.
- [ ] **4.6** Tests (mock repos via `unittest.mock.AsyncMock` returning canned model instances). Per service file:
  - `test_<svc>_scopes_by_workspace`: assert repo called with `ctx.workspace_id` filter.
  - `test_<svc>_get_404_when_cross_workspace`: forge a row from another workspace, ensure service returns None / raises 404.
  - `test_<svc>_redacts_secrets` (for IntegrationService): assert `secrets_encrypted` never in returned DTO.
  - `test_analytics_flaky_threshold`: build outcome history with variance 0.25 → flagged; variance 0.05 → not flagged; sampleSize 2 → not flagged.
- [ ] **4.7** `uv run pytest apps/api/tests/services -q` — green. `uv run mypy apps/api` — clean.
- [ ] **4.8** Commit: `feat(api): add service layer with tenant scoping and tier decorator`.

---

## Task 5 — Capability endpoint full implementation

**Path:** `apps/api/src/suitest_api/routers/capabilities.py` (replace M0 stub)
**Schema:** `packages/shared/src/suitest_shared/schemas/capabilities.py`
**Tests:** `apps/api/tests/test_capabilities.py`

### Goal

Replace the M0 hard-coded `{"tier": "ZERO", ...}` stub with a real resolver that:

1. Reads `SUITEST_LLM_PROVIDER`, `SUITEST_LLM_BASE_URL`, `SUITEST_LLM_API_KEY`, `SUITEST_LLM_MODEL`, `SUITEST_EMBEDDINGS_BACKEND`, `SUITEST_EMBEDDINGS_MODEL` at app startup and stores the resolved `Capabilities` object in `app.state.capabilities`.
2. If a workspace context is present (header or path), overlays `WorkspaceCapability` row values on top (per CAPABILITY_TIERS §11.2 precedence: workspace `LLMConfig` > env).
3. Returns the full JSON shape from CAPABILITY_TIERS.md §10.

### Steps

- [ ] **5.1** Implement `packages/core/suitest_core/capabilities.py::resolve_tier()` per CAPABILITY_TIERS §3 verbatim — sets of LOCAL_PROVIDERS / CLOUD_PROVIDERS, raise `ConfigError` for misconfig.
- [ ] **5.2** `resolve_embeddings() -> EmbeddingsConfig` per §3 — backend ∈ `{none, fastembed, openai, cohere}`, model + dim defaults.
- [ ] **5.3** `Capabilities` Pydantic v2 model in `packages/shared/src/suitest_shared/schemas/capabilities.py`:
  ```python
  class LLMSection(BaseModel):
      provider: str
      model: str | None
      base_url: str | None

  class EmbeddingsSection(BaseModel):
      enabled: bool
      backend: str
      model: str | None = None
      dim: int | None = None

  class FeaturesSection(BaseModel):
      manual_tcm: bool
      deterministic_runner: bool
      deterministic_generator_openapi: bool
      deterministic_generator_recorder: bool
      deterministic_generator_crawler: bool
      ai_generation: bool
      ai_execution_agentic: bool
      ai_diagnose: bool
      ai_conversation: bool
      semantic_search: bool
      fts_search: bool
      auto_defect_filing_ai: bool
      auto_defect_filing_rule: bool

  class AutonomySection(BaseModel):
      available: list[str]
      default: str

  class Capabilities(BaseModel):
      tier: Tier
      llm: LLMSection
      embeddings: EmbeddingsSection
      features: FeaturesSection
      autonomy: AutonomySection
      version: str
      mcp_providers: list[McpProviderPublic] = Field(default_factory=list, alias="mcpProviders")
      build: str | None = None
      model_config = ConfigDict(populate_by_name=True)
  ```
- [ ] **5.4** Mapping table (encoded in `packages/core/suitest_core/capabilities.py::compute_features(tier, embeddings)`):
  - ZERO → all `manual_tcm/deterministic_*` true; all `ai_*` false; `semantic_search = embeddings.enabled`; `fts_search = true`; `auto_defect_filing_ai = false`; `auto_defect_filing_rule = true`.
  - LOCAL → above + all `ai_*` true.
  - CLOUD → same as LOCAL.
- [ ] **5.5** Autonomy defaults: ZERO → `available=["manual"], default="manual"`; LOCAL/CLOUD → `available=["manual","assist","semi_auto","auto"], default="assist"`.
- [ ] **5.6** Startup hook: in `apps/api/src/suitest_api/main.py` lifespan, call `resolve_tier()` + `resolve_embeddings()` and stash on `app.state.capabilities` (a `Capabilities` instance with empty `mcp_providers`, version from `importlib.metadata.version("suitest-api")`).
- [ ] **5.7** Router `GET /capabilities`:
  - No auth required (per API.md §3.0).
  - If `X-Workspace-Id` header present and the workspace exists, fetch `WorkspaceCapability` + active `LLMConfig` rows, build overlay (tier from `LLMConfig.provider` if set, else env tier), join `McpProvider` rows. Otherwise return the app-state base capabilities.
  - Tier badge `version` from `app.state.capabilities.version`.
- [ ] **5.8** Router `GET /capabilities/health` — returns `{"tier": ..., "status": "ok", "uptimeSec": <int>}` (uptime captured at app startup).
- [ ] **5.9** Tests (parametrised over env permutations using `monkeypatch.setenv`):
  - `test_capabilities_zero_default`: no env → tier ZERO, all `ai_*=false`, autonomy default `manual`.
  - `test_capabilities_local_ollama`: `SUITEST_LLM_PROVIDER=ollama`, `SUITEST_LLM_BASE_URL=http://localhost:11434` → tier LOCAL, ai features true.
  - `test_capabilities_local_missing_base_url_raises`: ollama without base_url → app fails to boot (`ConfigError` propagates).
  - `test_capabilities_cloud_anthropic`: `SUITEST_LLM_PROVIDER=anthropic`, `SUITEST_LLM_API_KEY=sk-x` → tier CLOUD.
  - `test_capabilities_cloud_missing_key_raises`: anthropic without key → `ConfigError`.
  - `test_capabilities_cloud_bedrock_no_key_ok`: `SUITEST_LLM_PROVIDER=bedrock` without key → tier CLOUD (IAM).
  - `test_capabilities_embeddings_fastembed`: `SUITEST_EMBEDDINGS_BACKEND=fastembed` → `embeddings.dim=384`, `semantic_search=true`.
  - `test_capabilities_embeddings_openai`: backend openai → dim 1536.
  - `test_capabilities_embeddings_none`: default → `enabled=false`, `semantic_search=false`.
  - `test_capabilities_workspace_overlay`: insert `WorkspaceCapability(tier=CLOUD, autonomy=ASSIST)` for a workspace; call `GET /capabilities` with `X-Workspace-Id: ws_xxx` while env=ZERO → response shows CLOUD (DB overlay wins).
  - `test_capabilities_unknown_workspace_returns_base`: unknown ws id → returns env-derived response (no 404, no overlay).
  - `test_capabilities_response_matches_spec_shape_zero`: snapshot test against the ZERO sample JSON in CAPABILITY_TIERS §10.
  - `test_capabilities_response_matches_spec_shape_cloud`: snapshot vs the CLOUD sample.
- [ ] **5.10** `uv run pytest apps/api/tests/test_capabilities.py -q` — green.
- [ ] **5.11** Commit: `feat(api): implement /capabilities endpoint with env + workspace overlay`.

---

## Task 6 — Audit log middleware

**Path:** `packages/db/src/suitest_db/audit.py`
**Middleware:** `apps/api/src/suitest_api/middleware/audit.py`
**Tests:** `packages/db/tests/test_audit_listener.py` + `apps/api/tests/test_audit_middleware.py`

### Goal

Every mutation flushed by SQLAlchemy must emit an `AuditLog` row capturing `(workspace_id, user_id, action, resource_type, resource_id, metadata=before/after diff, ip_address, user_agent)`. M1a has no mutating endpoints, so the listener is verified via low-level repo writes in tests.

### Steps

- [ ] **6.1** Define `audit_ctx` ContextVar in `packages/db/src/suitest_db/audit.py`:
  ```python
  from contextvars import ContextVar
  from dataclasses import dataclass

  @dataclass
  class AuditContext:
      user_id: str | None
      workspace_id: str | None
      ip_address: str | None
      user_agent: str | None

  audit_ctx: ContextVar[AuditContext | None] = ContextVar("audit_ctx", default=None)
  ```
- [ ] **6.2** Register SQLAlchemy `after_flush` event listener (NOT `before_flush` — we need pk-resolved IDs):
  ```python
  from sqlalchemy import event
  from sqlalchemy.orm import Session

  AUDITED_TABLES = {  # tables we care about; explicit allowlist
      "test_cases", "test_steps", "case_tags", "runs", "run_steps", "artifacts",
      "defects", "external_issues", "requirements", "requirement_links",
      "integrations", "documents", "document_chunks",
      "llm_configs", "workspace_capabilities", "mcp_providers",
      "memberships", "projects", "suites",
  }

  def _diff(obj, attrs) -> dict:
      ...

  def _record(session: Session, target, action: str) -> None:
      ctx = audit_ctx.get()
      if ctx is None or ctx.workspace_id is None:
          return  # background tasks / migrations skip
      if target.__tablename__ not in AUDITED_TABLES:
          return
      from .models.audit import AuditLog  # late import to avoid cycle
      resource_id = getattr(target, "public_id", None) or getattr(target, "id")
      meta = {"changes": _diff(target, ...)} if action == "update" else None
      row = AuditLog(
          workspace_id=ctx.workspace_id,
          user_id=ctx.user_id,
          action=action,
          resource_type=target.__tablename__,
          resource_id=str(resource_id),
          metadata=meta,
          ip_address=ctx.ip_address,
          user_agent=ctx.user_agent,
      )
      session.add(row)

  @event.listens_for(Session, "after_flush")
  def _after_flush(session: Session, flush_context):
      for obj in session.new:
          _record(session, obj, "insert")
      for obj in session.dirty:
          if session.is_modified(obj, include_collections=False):
              _record(session, obj, "update")
      for obj in session.deleted:
          _record(session, obj, "delete")
  ```
- [ ] **6.3** Register at package import (`packages/db/src/suitest_db/__init__.py`) — listener is global, fires for every session.
- [ ] **6.4** ASGI middleware in `apps/api/src/suitest_api/middleware/audit.py`:
  - On request entry, extract `request.client.host`, `request.headers.get("user-agent")`, `current_user.id` (if authenticated), `X-Workspace-Id` header.
  - `audit_ctx.set(AuditContext(...))` then `await call_next(request)`. Reset token after.
  - Mount middleware in `main.py` **before** the route handler chain.
- [ ] **6.5** Tests at the DB listener level (no HTTP):
  - `test_audit_listener_inserts_row_on_create`: set `audit_ctx`, instantiate a `TestCase` via factory through a real session, flush, query `AuditLog` rows — exactly one with `action="insert"`, matching `resource_id`.
  - `test_audit_listener_skips_unaudited_table`: insert a `User` row (not in AUDITED_TABLES) → zero AuditLog rows.
  - `test_audit_listener_no_context_skips`: leave `audit_ctx` empty → insert → zero rows.
  - `test_audit_listener_update_captures_changes`: insert defect, update its status, assert audit row metadata reflects `{"changes": {"status": ["OPEN", "IN_PROGRESS"]}}`. The `_diff` helper should use `sqlalchemy.orm.attributes.get_history(obj, attr)` for each modified attr.
  - `test_audit_listener_delete_records`: delete a Defect → row with action="delete".
- [ ] **6.6** Tests at the HTTP middleware level (FastAPI TestClient):
  - `test_audit_middleware_sets_context_from_headers`: hit any route with `X-Workspace-Id: ws_x`, mock service that inserts a row inside, then assert the row's audit log has correct ip/ua/user_id.
- [ ] **6.7** Commit: `feat(db): add audit log SQLAlchemy listener + request middleware`.

---

## Task 7 — Read-only REST endpoints

All endpoints below are **GET only**. Each sub-task: Pydantic schemas → router → tests → commit.

### Shared scaffolding (do before 7a)

- [ ] **7.0.1** Pagination response wrapper `packages/shared/src/suitest_shared/schemas/pagination.py`:
  ```python
  class PageMeta(BaseModel):
      next_cursor: str | None = Field(default=None, alias="nextCursor")
      limit: int

  class Page[T](BaseModel):
      items: list[T]
      meta: PageMeta
  ```
- [ ] **7.0.2** Common query model:
  ```python
  class CursorParams(BaseModel):
      cursor: str | None = None
      limit: int = Field(20, ge=1, le=100)
  ```
- [ ] **7.0.3** Auth dependency `Depends(current_active_user)` already exists from M0; confirm it raises 401 when missing.
- [ ] **7.0.4** Workspace dependency `Depends(require_workspace_membership)`:
  - Extract `X-Workspace-Id` header.
  - Fetch `Membership(user_id=current_user.id, workspace_id=header)` — none → 403.
  - Returns `TenantContext`.

### Task 7a — Auth + Workspaces

**Schema:** `packages/shared/src/suitest_shared/schemas/workspace.py`
**Router:** `apps/api/src/suitest_api/routers/workspaces.py` + `auth.py`
**Tests:** `apps/api/tests/test_workspaces.py`

Endpoints (per API.md §3.1):
- `GET /auth/me` → `{ id, email, name, avatar_url, memberships: [{workspace_id, role, workspace: {...}}] }`.
- `GET /workspaces` → list for current user (no cursor; small list expected).
- `GET /workspaces/:id` → detail; 403 if not a member.
- `GET /workspaces/:id/members` → list of `{user_id, email, name, role, joined_at}`.

- [ ] **7a.1** Schemas: `UserPublic`, `MembershipPublic`, `WorkspacePublic`, `WorkspaceDetail`, `MeResponse`.
- [ ] **7a.2** Implement routers, mount under `/api/v1`.
- [ ] **7a.3** Tests:
  - `test_me_returns_user_and_memberships`.
  - `test_me_requires_auth`: no cookie → 401.
  - `test_workspaces_lists_only_members`: user A in ws1 only → `GET /workspaces` returns just ws1 even when ws2 exists.
  - `test_workspace_detail_403_when_non_member`.
  - `test_workspace_members_lists_all`.
- [ ] **7a.4** Commit: `feat(api): add GET /auth/me and workspace read endpoints`.

### Task 7b — Projects + Suites

**Schemas:** `project.py`, `suite.py`
**Router:** `routers/projects.py`, `routers/suites.py`
**Tests:** `test_projects.py`, `test_suites.py`

Endpoints:
- `GET /projects` (filter by workspace via header).
- `GET /projects/:id`.
- `GET /suites?projectId=...`.
- `GET /suites/:id`.

- [ ] **7b.1** Schemas: `ProjectPublic`, `SuitePublic` (with `case_count` computed).
- [ ] **7b.2** Routers — all enforce `Depends(require_workspace_membership)`.
- [ ] **7b.3** Tests:
  - `test_projects_list_paginated`: seed 25 projects → request `limit=10` → 10 items + cursor → page 2 → 10 + cursor → page 3 → 5 + no cursor.
  - `test_project_detail_404_when_cross_workspace`.
  - `test_suites_list_filtered_by_project`.
  - `test_suite_case_count_accurate`: seed 3 cases for suite, response shows `case_count=3`.
- [ ] **7b.4** Commit: `feat(api): add project + suite read endpoints with pagination`.

### Task 7c — Test cases

**Schema:** `test_case.py`
**Router:** `routers/test_cases.py`
**Tests:** `test_test_cases.py`

Endpoints:
- `GET /test-cases` with filters `?suiteId&status&source&priority&tag&q&cursor&limit`.
- `GET /test-cases/:id` — returns case + steps + tags.
- `GET /test-cases/:id/steps` — steps only (used by step editor pre-load).

- [ ] **7c.1** Schemas: `TestStepPublic` (with computed `executable: bool` populated by service using current workspace tier), `TestCasePublic`, `TestCaseListItem` (no steps), `TestCaseDetail` (with steps).
- [ ] **7c.2** Service decorates steps: for each step, compute `executable` by passing `(step, ctx_capabilities.tier)`. `TestStepPublic.executable` is a regular field, not Pydantic computed — set at construction in the service.
- [ ] **7c.3** Routers + filter parsing.
- [ ] **7c.4** Tests:
  - `test_list_test_cases_by_suite`.
  - `test_list_test_cases_filter_status_active`: 3 ACTIVE + 2 DEPRECATED seeded → `?status=ACTIVE` returns 3.
  - `test_list_test_cases_filter_q`: case names "Login flow" / "Checkout" / "Login error" → `?q=login` returns 2 (case-insensitive ILIKE).
  - `test_list_test_cases_filter_tag`: seed with tags, filter by `?tag=smoke`.
  - `test_get_test_case_includes_steps_in_order`.
  - `test_get_test_case_step_executable_zero_tier`: ZERO tier + step has only `action` → `executable=false`. Same step + CLOUD tier (overlay via workspace cap) → `executable=true`.
  - `test_get_test_case_404_when_cross_workspace`.
  - `test_list_test_cases_pagination_cursor_stable`: insert two cases with identical created_at — pagination still progresses (tiebreak on id).
- [ ] **7c.5** Commit: `feat(api): add test case read endpoints with filters + executable per tier`.

### Task 7d — Requirements + Traceability

**Schema:** `requirement.py`, `traceability.py`
**Router:** `routers/requirements.py`, `routers/traceability.py`

Endpoints:
- `GET /requirements?projectId=...&cursor&limit`.
- `GET /requirements/:id` — detail with linked case publicIds + linked defect publicIds.
- `GET /traceability/matrix?projectId=...` — shape per API.md §3.7.

- [ ] **7d.1** Schemas: `RequirementListItem` (with `link_count`), `RequirementDetail`, `TraceabilityMatrix`.
- [ ] **7d.2** Matrix query: build via three repo calls (requirements by project, cases by project, defects by project) + a join query for links — combine in service. Avoid N+1; preload via `selectinload`.
- [ ] **7d.3** Tests:
  - `test_list_requirements_with_link_count`.
  - `test_get_requirement_detail_lists_cases_and_defects`.
  - `test_traceability_matrix_shape`: seed 2 reqs, 3 cases, 2 defects, 4 links → assert response shape matches API.md §3.7.
  - `test_traceability_matrix_empty_project`.
- [ ] **7d.4** Commit: `feat(api): add requirement + traceability read endpoints`.

### Task 7e — Runs + RunSteps + Logs + Artifacts

**Schema:** `run.py`
**Router:** `routers/runs.py`
**Tests:** `test_runs.py`

Endpoints (all GET):
- `GET /runs?status&projectId&branch&env&cursor&limit`.
- `GET /runs/:id` — detail with summary (`total_steps`, `passed_steps`, `failed_steps`, `duration_ms`).
- `GET /runs/:id/steps` — list of run steps with outcomes + linked case `publicId`.
- `GET /runs/:id/logs?cursor=…` — streams stdout/stderr chunks (cursor-paginated; treats each RunStep.stdout/stderr as a chunk, then yields a synthesised log line per `run.step.log` audit, if available). For M1a the implementation simply concatenates `RunStep.stdout` + `RunStep.stderr` in step_order, returning a paginated text stream.
- `GET /runs/:id/artifacts` — list.
- `GET /runs/:id/artifacts/:artifactId` — generates a signed URL via MinIO SDK (mock in tests). Response: `{"url": "https://...", "expiresAt": "..."}`.

- [ ] **7e.1** Schemas: `RunListItem`, `RunDetail`, `RunStepPublic`, `RunLogPage`, `ArtifactPublic`, `ArtifactSignedUrl`.
- [ ] **7e.2** Signed URL helper `apps/api/src/suitest_api/services/artifact_signing.py` — wraps `minio.Minio.presigned_get_object`. If `Artifact.url` starts with `file://` (single-host volume mode), redirect to `/artifacts/raw/{id}` static route instead (don't implement raw route in M1a; just return a placeholder URL and a `kind` discriminator).
- [ ] **7e.3** Tests:
  - `test_list_runs_filter_by_status`.
  - `test_list_runs_filter_by_branch_env`.
  - `test_get_run_detail_summary_correct`: seed 5 RunSteps (3 PASS, 1 FAIL, 1 ERROR) → response shows summary.
  - `test_get_run_steps_ordered`.
  - `test_get_run_logs_paginated`.
  - `test_get_run_artifacts_lists_all`.
  - `test_get_artifact_signed_url_s3`: mock MinIO, assert call args.
  - `test_get_artifact_signed_url_file_scheme_returns_placeholder`.
  - `test_get_run_404_cross_workspace`.
- [ ] **7e.4** Commit: `feat(api): add run, run-step, log, and artifact read endpoints`.

### Task 7f — Defects

**Schema:** `defect.py`
**Router:** `routers/defects.py`
**Tests:** `test_defects.py`

Endpoints:
- `GET /defects?status&severity&assigneeId&component&cursor&limit`.
- `GET /defects/:id` — detail incl. linked case publicId, run publicId, requirement publicId, external issues list.
- `GET /defects/:id/timeline` — list of audit_log rows for `resource_type=defects, resource_id=<defect.public_id or id>` ordered ASC.

- [ ] **7f.1** Schemas: `DefectListItem`, `DefectDetail`, `DefectTimelineEntry`.
- [ ] **7f.2** Timeline composition rule: prepend a synthetic `{"action": "created", "at": defect.created_at, "user_id": defect.created_by}` then audit rows.
- [ ] **7f.3** Tests:
  - `test_list_defects_filter_status_open`.
  - `test_list_defects_filter_severity_critical`.
  - `test_get_defect_detail_includes_external_issues`.
  - `test_get_defect_timeline_includes_creation_and_audit_rows`.
  - `test_get_defect_404_cross_workspace`.
- [ ] **7f.4** Commit: `feat(api): add defect read endpoints + timeline`.

### Task 7g — Integrations

**Schema:** `integration.py`
**Router:** `routers/integrations.py`
**Tests:** `test_integrations.py`

Endpoints:
- `GET /integrations?kind=...`.
- `GET /integrations/:id` — detail with **redacted** secrets (`"secrets": {"redacted": true, "hint": "sk-…last4"}` or `null` if absent).

- [ ] **7g.1** Schemas: `IntegrationPublic` (config visible; secrets always redacted).
- [ ] **7g.2** Redaction helper: if `secrets_encrypted is not None`, set response `secrets_redacted=true` and surface a `hint` (last 4 chars of decrypted plaintext via `EncryptedBytes` round-trip — the **only** time we decrypt for a read endpoint, and only the last 4 are returned).
- [ ] **7g.3** Tests:
  - `test_list_integrations_filter_kind_jira`.
  - `test_get_integration_secrets_always_redacted`: assert response JSON contains no full secret string (search for `"sk-realkey-"` should fail).
  - `test_get_integration_404_cross_workspace`.
- [ ] **7g.4** Commit: `feat(api): add integration read endpoints with redacted secrets`.

### Task 7h — Documents

**Schema:** `document.py`
**Router:** `routers/documents.py`
**Tests:** `test_documents.py`

Endpoints:
- `GET /documents?kind&cursor&limit`.
- `GET /documents/:id` — detail (no chunks in M1a).

- [ ] **7h.1** Schemas: `DocumentListItem` (chunk_count computed), `DocumentDetail`.
- [ ] **7h.2** Tests:
  - `test_list_documents_filter_kind_prd`.
  - `test_document_detail_chunk_count`.
  - `test_get_document_404_cross_workspace`.
- [ ] **7h.3** Commit: `feat(api): add document read endpoints`.

### Task 7i — Analytics

**Schema:** `analytics.py`
**Router:** `routers/analytics.py`
**Tests:** `test_analytics.py`

Endpoints:
- `GET /analytics/kpis?projectId&period=7d` → `{ passRate, runCount, avgDurationMs, defectsOpen }`.
- `GET /analytics/pass-rate?projectId&period=30d` → `{ series: [{date, passRate}], total }`.
- `GET /analytics/coverage?projectId` → `{ bySuite: [{suiteId, name, total, covered, coverage}], byRequirement: [{requirementId, total, covered}] }`.
- `GET /analytics/flaky?projectId&minRate=0.20` → `[{caseId, publicId, flakeRate, sampleSize}]`.
- `GET /analytics/heatmap?projectId&period=14d` → 2D grid `{day, hour, count}[]`.
- `GET /analytics/readiness?projectId` → `{ score, blockers: [{type, message, ref}] }`.

- [ ] **7i.1** Schemas: one model per endpoint output, matching the shapes above.
- [ ] **7i.2** Period parser helper: accept `7d`, `30d`, `90d` (regex `^(\d+)d$`); reject others with 400.
- [ ] **7i.3** Flaky rule (already implemented in `AnalyticsService` from Task 4): re-export here.
- [ ] **7i.4** Readiness rule (deterministic, no LLM): `score = 100 - (10 * open_critical_defects) - (5 * open_high_defects) - (2 * unlinked_requirements_count)`. Blockers list: each open CRITICAL defect = blocker; each requirement without a linked case = blocker. Cap score at `[0, 100]`.
- [ ] **7i.5** Heatmap: SQL `SELECT date_trunc('day', created_at) AS day, EXTRACT(HOUR FROM created_at) AS hour, COUNT(*) FROM runs WHERE project_id=:p AND created_at >= :since GROUP BY day, hour`.
- [ ] **7i.6** Tests:
  - `test_kpis_seven_day_window`.
  - `test_pass_rate_time_series_ordered_ascending`.
  - `test_coverage_by_suite_correct`.
  - `test_coverage_by_requirement_correct`.
  - `test_flaky_endpoint_threshold_default_20pct`: deterministic seed.
  - `test_flaky_endpoint_min_rate_query_param`: pass `?minRate=0.10` widens results.
  - `test_heatmap_day_hour_grid`.
  - `test_readiness_score_caps_at_zero_when_many_blockers`.
  - `test_readiness_blockers_list`.
  - `test_analytics_invalid_period_400`.
- [ ] **7i.7** Commit: `feat(api): add analytics read endpoints (kpis, pass-rate, coverage, flaky, heatmap, readiness)`.

---

## Task 8 — Public ID generation

**Path:** `packages/db/src/suitest_db/public_id.py`
**Migration:** `packages/db/alembic/versions/<rev>_public_id_function.py`
**Tests:** `packages/db/tests/test_public_id.py`

### Goal

Per-workspace, per-prefix Postgres sequence-backed public IDs. Used at write time (M1d) but the **function + event hooks** ship in M1a so seeding can produce realistic `TC-1000`, `R-1000`, etc.

### Steps

- [ ] **8.1** Alembic migration `add generate_public_id function`:
  - `op.execute(<CREATE OR REPLACE FUNCTION generate_public_id(prefix TEXT, workspace_id TEXT) ... LANGUAGE plpgsql>)` — body verbatim from DATA_MODEL §8.
  - Downgrade: `op.execute("DROP FUNCTION IF EXISTS generate_public_id(TEXT, TEXT)")`.
- [ ] **8.2** Python wrapper `generate_public_id(db, prefix, workspace_id)` per DATA_MODEL §8.
- [ ] **8.3** SQLAlchemy `before_insert` event listeners for `TestCase`, `Run`, `Requirement`, `Defect`:
  ```python
  @event.listens_for(TestCase, "before_insert")
  def _tc_public_id(mapper, conn, target):
      if target.public_id:
          return
      # need workspace_id; for TestCase that means suite -> project -> workspace
      # easier: caller passes workspace_id explicitly via a transient attr
      ws_id = getattr(target, "_workspace_id_for_pubid", None)
      if not ws_id:
          raise RuntimeError("public_id requires _workspace_id_for_pubid transient attr")
      target.public_id = conn.execute(
          text("SELECT generate_public_id(:p, :w)"), {"p": "TC", "w": ws_id}
      ).scalar_one()
  ```
  Prefix map: `TestCase → "TC"`, `Run → "R"`, `Requirement → "REQ"`, `Defect → "SUIT"` (per DATA_MODEL §8).
- [ ] **8.4** Repo helpers (`TestCaseRepo.create`, `RunRepo.create`, etc.) set `target._workspace_id_for_pubid = ctx.workspace_id` before flush.
- [ ] **8.5** Tests:
  - `test_generate_public_id_increments_per_workspace_prefix`:
    - In ws_A: create 3 cases via repo → public_ids `TC-1000`, `TC-1001`, `TC-1002`.
    - In ws_B: create 1 case → `TC-1000` (separate sequence).
    - In ws_A: create 1 run → `R-1000` (separate prefix).
  - `test_generate_public_id_missing_workspace_raises`: create case without setting transient attr → `RuntimeError`.
  - `test_generate_public_id_idempotent_when_already_set`: pre-set `public_id="TC-9999"` → listener leaves it.
- [ ] **8.6** Commit: `feat(db): add public ID Postgres function + per-entity event listeners`.

---

## Task 9 — Seed script

**Path:** `packages/db/src/suitest_db/seed.py`
**CLI:** `uv run python -m suitest_db.seed`
**Tests:** `packages/db/tests/test_seed.py` + CI smoke test in `apps/api/tests/test_seed_e2e.py`

### Goal

Idempotent, factory-backed seeder building **Nusantara Retail** workspace per DATA_MODEL §11 + the additional shape requested for M1a: 9 integrations (some connected), broader case mix.

### Steps

- [ ] **9.1** Build a `Seeder` class wrapping an `AsyncSession`. Methods:
  - `ensure_workspace()` — `INSERT ... ON CONFLICT (slug) DO NOTHING; SELECT ...`.
  - `ensure_users()` — Maya (owner), Ari (admin), Dimas (QA).
  - `ensure_memberships()`.
  - `ensure_project()` — E-commerce Web.
  - `ensure_suites()` — 4 (Auth, Checkout, Catalog, Admin).
  - `ensure_test_cases()` — 18 cases across the 4 suites, mixing `CaseSource.MANUAL` (10), `IMPORT` (4), `RECORDER` (2), `HEURISTIC_CRAWL` (2). Vary priorities P0–P3. Each case gets 3–5 steps with mostly `code` set + `mcp_provider` matching `target_kind`.
  - `ensure_runs()` — 5 runs: 2 PASS, 2 FAIL, 1 ERROR. Each with `tier_at_runtime=Tier.ZERO`. Populate `RunStep` rows for each step of the run's cases (use simple "all pass" / "step 3 fail" templates). Generate `Artifact` rows (1 screenshot per failed step).
  - `ensure_defects()` — 3 defects with `agent_diagnosis_kind=MANUAL_TRIAGE`, severities CRITICAL/HIGH/MEDIUM, statuses OPEN/IN_PROGRESS/RESOLVED.
  - `ensure_requirements()` — 6 (REQ-401..406), some linked to cases, one unlinked (so readiness blocker test works).
  - `ensure_integrations()` — 9 rows: GitHub (connected, encrypted PAT), Jira (connected), Slack (disconnected — no secrets), Linear (disconnected), Jenkins (disconnected), MCP_BROWSER_USE, MCP_PLAYWRIGHT, MCP_API, MCP_POSTGRES. Connected ones have `status="active"` + encrypted secret; disconnected ones have `status="disconnected"` + no secret.
  - `ensure_mcp_providers()` — 2 rows: `playwright-mcp` default FE_WEB, `api-mcp` default BE_REST.
  - `ensure_llm_config()` — 1 row with `provider="none"`, `is_active=False`.
  - `ensure_workspace_capability()` — `tier=ZERO, autonomy=MANUAL`.
  - `ensure_prompt_version()` — `v1/generate-from-prd` v1.0.0.
- [ ] **9.2** CLI entrypoint: `python -m suitest_db.seed` reads `SUITEST_DATABASE_URL`, opens session, runs all `ensure_*` in order.
- [ ] **9.3** Idempotency: each `ensure_*` checks for existing rows by stable unique key (workspace slug, user email, project slug, suite name within project, case name within suite, integration `(workspace_id, kind, name)` synthetic).
- [ ] **9.4** Reuse factory-boy / polyfactory definitions from Task 3.4 where possible, but keep the seeder deterministic — set fixed cuid seeds via `cuid2.Cuid(length=24, fingerprint="suitest-seed")` so re-runs converge.
- [ ] **9.5** Tests:
  - `test_seed_idempotent`: run seeder, count rows; run again, count unchanged.
  - `test_seed_workspace_shape`: after seed, assert `Workspace(slug="nusantara-retail")` exists with expected `name="Nusantara Retail"`.
  - `test_seed_eighteen_cases`.
  - `test_seed_five_runs_with_correct_outcomes`.
  - `test_seed_three_defects`.
  - `test_seed_nine_integrations_mixed_status`.
  - `test_seed_capability_zero_manual`.
- [ ] **9.6** CI smoke test (`apps/api/tests/test_seed_e2e.py`):
  - `pytest` fixture spins API+PG, runs seeder once, hits `GET /api/v1/test-cases` with the Maya session cookie → asserts `len(items) == 18`.
- [ ] **9.7** Commit: `feat(db): add Nusantara Retail seed script with 18 cases + 9 integrations`.

---

## Task 10 — OpenAPI export + drift gate

**Path:** `scripts/export-openapi.py`
**Committed artifact:** `packages/shared/openapi.json`
**CI job:** `.github/workflows/ci.yml` (add a step)

### Goal

Lock the wire contract by exporting OpenAPI 3.1 on every CI run and diffing against the committed snapshot. Drift = PR failure unless `packages/shared/openapi.json` is regenerated and committed.

### Steps

- [ ] **10.1** Confirm FastAPI exposes `/openapi.json` (default behaviour; no extra code).
- [ ] **10.2** Script `scripts/export-openapi.py`:
  - Boots the FastAPI app via `from suitest_api.main import app; from fastapi.testclient import TestClient`.
  - Writes `client.get("/openapi.json").json()` to `packages/shared/openapi.json` (pretty-printed, `sort_keys=True` so diffs are stable).
  - Exits 0 on success.
- [ ] **10.3** Tests:
  - `test_openapi_export_writes_file`: monkeypatch path to tmp, run script, assert file written and parseable as JSON.
  - `test_openapi_export_stable`: run twice → identical bytes (key sort).
- [ ] **10.4** CI step:
  ```yaml
  - name: Export OpenAPI
    run: uv run python scripts/export-openapi.py /tmp/openapi.json
  - name: Diff committed snapshot
    run: diff -u packages/shared/openapi.json /tmp/openapi.json
  ```
- [ ] **10.5** Commit: `feat(shared): export OpenAPI snapshot + CI drift gate`.

---

## Task 11 — Observability

**Path:** `apps/api/src/suitest_api/observability.py`
**Tests:** `apps/api/tests/test_observability.py`

### Goal

Wire OpenTelemetry (traces + metrics), Prometheus `/metrics`, and structlog JSON logging. Auto-instrument FastAPI / SQLAlchemy / httpx / asyncpg. Custom span attributes for multi-tenant attribution.

### Steps

- [ ] **11.1** Dependencies (already in `pyproject.toml` from M0 if seeded; otherwise add):
  - `opentelemetry-distro`, `opentelemetry-exporter-otlp-proto-http`,
  - `opentelemetry-instrumentation-fastapi`,
  - `opentelemetry-instrumentation-sqlalchemy`,
  - `opentelemetry-instrumentation-httpx`,
  - `opentelemetry-instrumentation-asyncpg`,
  - `prometheus-fastapi-instrumentator`,
  - `structlog`.
- [ ] **11.2** `observability.py::setup_observability(app)`:
  - Reads `OTEL_EXPORTER_OTLP_ENDPOINT` (default `http://localhost:4318`).
  - Configures TracerProvider + OTLPSpanExporter (HTTP/protobuf).
  - Calls `FastAPIInstrumentor.instrument_app(app)`, `SQLAlchemyInstrumentor().instrument(engine=engine)`, etc.
  - Adds `prometheus_fastapi_instrumentator.Instrumentator().instrument(app).expose(app, endpoint="/metrics")`.
  - Configures structlog with `JSONRenderer()` to stdout.
- [ ] **11.3** Custom span attributes — small middleware that, on each request, picks up `audit_ctx` and sets `current_span.set_attributes({"workspace.id": ctx.workspace_id, "user.id": ctx.user_id, "capabilities.tier": app.state.capabilities.tier.value})`.
- [ ] **11.4** Tests:
  - `test_metrics_endpoint_exposes_default_metrics`: `GET /metrics` returns text containing `# HELP http_server_requests`.
  - `test_request_logs_are_json`: capture log output, assert each line parses as JSON with keys `event`, `level`, `time`, `request_id`.
  - `test_span_attributes_set` — use `opentelemetry.sdk.trace.in_memory_exporter.InMemorySpanExporter`, hit a route, assert exported span has `workspace.id` attribute when `X-Workspace-Id` provided.
- [ ] **11.5** Commit: `feat(api): wire OpenTelemetry, Prometheus, structlog`.

---

## Task 12 — Rate limiting

**Path:** `apps/api/src/suitest_api/middleware/ratelimit.py`
**Tests:** `apps/api/tests/test_ratelimit.py`

### Goal

Apply rate limits per API.md §5 using `slowapi` with a Redis backend (Redis already in M0 docker-compose). Different limits per audience (cookie session vs bearer token).

### Steps

- [ ] **12.1** Add `slowapi` to deps.
- [ ] **12.2** Initialise `limiter = Limiter(key_func=_audience_key, storage_uri=os.environ["SUITEST_REDIS_URL"])`. `_audience_key`: returns `f"user:{user.id}"` for cookie session, `f"token:{token_id}"` for Bearer (compute token_id = sha256(token)[:16]).
- [ ] **12.3** Default limit decorator on all routers: `@limiter.limit("600/minute")` for cookie users, `@limiter.limit("1000/minute")` for Bearer. Implement via per-route `Depends` rather than decorator stacking (slowapi supports this via `RateLimitExceeded` exception handler).
- [ ] **12.4** Per-route override map (per §5):
  - Default web user: 600/minute.
  - Bearer token: 1000/minute.
  - Webhook routes (M1 future): unlimited (don't add yet, but document).
  - Agent routes (M3 future): 60/minute per workspace.
  - Generation (M3 future): 20/minute per workspace.
- [ ] **12.5** 429 response includes `Retry-After` header (slowapi default).
- [ ] **12.6** Tests (use `fakeredis.aioredis`):
  - `test_ratelimit_under_threshold_passes`: 100 GETs in <1s succeed.
  - `test_ratelimit_over_threshold_429`: 601st GET → 429 + `Retry-After` header present.
  - `test_ratelimit_different_users_separate_buckets`: user A burst → user B unaffected.
  - `test_ratelimit_bearer_higher_threshold`: switch to Bearer key → tolerates more requests.
- [ ] **12.7** Commit: `feat(api): add per-audience rate limiting via slowapi + Redis`.

---

## Task 13 — DoD smoke E2E

**Path:** `apps/api/tests/test_m1a_smoke.py`
**Tag:** `v0.2.0-m1a` after green CI.

### Goal

Single happy-path E2E proving an authenticated user can browse the seeded workspace end to end via the documented endpoints. This is the single test that gets bound to the milestone tag.

### Steps

- [ ] **13.1** Test fixture: brings up Postgres testcontainer, runs migrations, runs seed, boots FastAPI via `TestClient`, performs FastAPI-Users login flow (`POST /auth/jwt/login` with `maya@suitest.io` / fixed seed password) and persists the cookie.
- [ ] **13.2** Test body (sequential):
  - `GET /capabilities` → tier == ZERO, autonomy.default == "manual".
  - `GET /auth/me` → email == "maya@suitest.io", memberships includes Nusantara Retail with role OWNER.
  - `GET /workspaces` → exactly one workspace (slug "nusantara-retail"). Capture `workspace.id`.
  - Set `X-Workspace-Id` header for the rest.
  - `GET /projects` → exactly 1 (E-commerce Web). Capture `project.id`.
  - `GET /suites?projectId=...` → 4 suites.
  - `GET /test-cases?suiteId=<first_suite>` → ≥1 case. Capture first `case.id`.
  - `GET /test-cases/<case_id>` → includes ≥1 step.
  - `GET /runs?projectId=...` → 5 runs.
  - `GET /runs/<first_run_id>` → has summary fields.
  - `GET /runs/<first_run_id>/steps` → ≥1 RunStep.
  - `GET /defects` → 3 defects.
  - `GET /defects/<first_defect_id>/timeline` → ≥1 entry (the "created" synthetic).
  - `GET /requirements?projectId=...` → 6.
  - `GET /traceability/matrix?projectId=...` → response shape check (3 keys).
  - `GET /integrations` → 9.
  - `GET /documents` → 0 (no documents in seed; spec only seeds prompt + integration data).
  - `GET /analytics/kpis?projectId=...&period=7d` → numeric `passRate`.
  - `GET /analytics/flaky?projectId=...` → list (may be empty).
  - `GET /analytics/readiness?projectId=...` → score 0–100.
- [ ] **13.3** Run `uv run pytest apps/api/tests/test_m1a_smoke.py -q` — green.
- [ ] **13.4** Commit + tag: `chore(release): cut v0.2.0-m1a candidate`. Then `git tag v0.2.0-m1a`.

---

## Self-review checklist (verify before declaring M1a complete)

1. [ ] Every table in DATA_MODEL.md §3 and §4 has: model file under `packages/db/src/suitest_db/models/`, Alembic migration, repo subclass, service (where applicable), and table-level tests.
2. [ ] Every GET endpoint in API.md §3.1–3.11 (excluding agent/generators/eval — those belong to M2/M3) is implemented and tested.
3. [ ] No placeholder routes; no `raise NotImplementedError`.
4. [ ] `/capabilities` returns the **full** shape from CAPABILITY_TIERS.md §10 — both ZERO and CLOUD snapshots are covered by snapshot tests.
5. [ ] Multi-tenant scoping (`workspace_id` filter) is asserted in **every** service test by mocking a cross-workspace row and confirming 404.
6. [ ] Capability/autonomy enforcement is **not** strict at the GET layer (read-only), but the `@require_tier(...)` decorator is present on every service method so M3 can flip the switch by changing the decorator's implementation.
7. [ ] No secret ever leaves the API in plaintext — `Integration` / `LLMConfig` / `McpProvider` responses redact via the schema layer (verified by tests grepping the response JSON for known seed plaintext values).
8. [ ] Audit-log listener installed, verified at the ORM level + ASGI middleware sets context per request.
9. [ ] OpenAPI snapshot committed; CI diff gate green.
10. [ ] Observability: spans visible in test exporter; `/metrics` endpoint returns Prometheus format; logs are JSON.
11. [ ] Rate limit: 429 path tested.
12. [ ] E2E smoke (Task 13) green in CI.

---

## Hard constraints recap

- This is a plan file. No code is written outside this document.
- All paths in this plan are **absolute from the repo root**. Don't deviate at implementation time.
- Conventional commits, one task or sub-task per commit.
- Pydantic v2, SQLAlchemy 2 `Mapped[]` annotations, async everywhere.
- Tests precede implementation (TDD). The task is "done" only when `uv run pytest <path>` is green AND `uv run mypy <pkg>` is clean AND `uv run ruff check <pkg>` is clean.
- No barrel `__init__.py` re-exports (CLAUDE.md §2.2).
- No `Any` in Python (CLAUDE.md §2.2). Use `TypedDict`, `Protocol`, or precise unions.
- Migrations are reviewed by eye; never trust autogen blindly for: JSONB defaults, check constraints, enum value additions, pgvector index types (DATA_MODEL.md §10).

---

## Appendix A — File tree after M1a

```
apps/api/src/suitest_api/
├── main.py
├── observability.py
├── deps/
│   ├── auth.py
│   ├── db.py
│   ├── scope.py
│   └── tier.py
├── middleware/
│   ├── audit.py
│   └── ratelimit.py
├── routers/
│   ├── analytics.py
│   ├── auth.py
│   ├── capabilities.py
│   ├── defects.py
│   ├── documents.py
│   ├── integrations.py
│   ├── projects.py
│   ├── requirements.py
│   ├── runs.py
│   ├── suites.py
│   ├── test_cases.py
│   ├── traceability.py
│   └── workspaces.py
└── services/
    ├── analytics_service.py
    ├── artifact_signing.py
    ├── capability_service.py
    ├── defect_service.py
    ├── document_service.py
    ├── integration_service.py
    ├── project_service.py
    ├── requirement_service.py
    ├── run_service.py
    ├── suite_service.py
    ├── test_case_service.py
    ├── traceability_service.py
    └── workspace_service.py

packages/core/suitest_core/
├── capabilities.py
└── crypto.py

packages/db/src/suitest_db/
├── __init__.py
├── audit.py
├── public_id.py
├── seed.py
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── <hash>_tenancy.py
│       ├── <hash>_projects_suites.py
│       ├── <hash>_test_cases.py
│       ├── <hash>_requirements.py
│       ├── <hash>_runs.py
│       ├── <hash>_defects.py
│       ├── <hash>_integrations.py
│       ├── <hash>_agent.py
│       ├── <hash>_documents.py
│       ├── <hash>_audit_logs.py
│       ├── <hash>_capability_tables.py
│       └── <hash>_public_id_function.py
├── models/
│   ├── __init__.py
│   ├── agent.py
│   ├── audit.py
│   ├── base.py
│   ├── case.py
│   ├── code_export.py
│   ├── defect.py
│   ├── document.py
│   ├── eval_run.py
│   ├── generator_run.py
│   ├── integration.py
│   ├── llm_config.py
│   ├── mcp_provider.py
│   ├── project.py
│   ├── prompt_version.py
│   ├── requirement.py
│   ├── run.py
│   ├── tenancy.py
│   └── workspace_capability.py
└── repositories/
    ├── audit_log.py
    ├── base.py
    ├── cursor.py
    ├── defect.py
    ├── document.py
    ├── integration.py
    ├── llm_config.py
    ├── mcp_provider.py
    ├── project.py
    ├── requirement.py
    ├── run.py
    ├── suite.py
    ├── test_case.py
    ├── workspace.py
    └── workspace_capability.py

packages/shared/src/suitest_shared/
├── domain/
│   └── enums.py
├── openapi.json
└── schemas/
    ├── analytics.py
    ├── capabilities.py
    ├── defect.py
    ├── document.py
    ├── integration.py
    ├── pagination.py
    ├── project.py
    ├── requirement.py
    ├── run.py
    ├── suite.py
    ├── test_case.py
    ├── traceability.py
    └── workspace.py

scripts/
└── export-openapi.py
```

---

## Appendix B — Test surface inventory

| Package | Test file count target |
|---------|------------------------|
| `packages/core/tests/` | 1 (crypto) |
| `packages/db/tests/` | 11 (one per model file) + 1 (audit listener) + 1 (public_id) + 1 (seed) |
| `packages/db/tests/repositories/` | 12 (one per repo) + 1 (cursor) |
| `apps/api/tests/services/` | 13 (one per service) |
| `apps/api/tests/` (routers) | 13 (one per router/resource) + 1 (capabilities) + 1 (observability) + 1 (ratelimit) + 1 (audit middleware) + 1 (seed e2e) + 1 (M1a smoke) |

Approx 60 test files, ≈ 220 individual test cases.

---

## Appendix C — Conventional commits log (expected order)

1. `feat(core): add AES-GCM crypto helper + EncryptedBytes type`
2. `feat(db): add users + memberships, extend workspaces with region`
3. `feat(db): add projects + suites`
4. `feat(db): add test cases, steps, and tags with MCP routing fields`
5. `feat(db): add requirements + traceability links`
6. `feat(db): add runs, run_steps, and artifacts with tier_at_runtime`
7. `feat(db): add defects + external issues with diagnosis_kind`
8. `feat(db): add integrations with AES-GCM-encrypted secrets column`
9. `feat(db): add agent sessions, messages, and tool calls`
10. `feat(db): add documents + chunks with variable-dim pgvector`
11. `feat(db): add audit log table`
12. `feat(db): add LLM config, capability, MCP providers, generator/prompt/eval/code-export tables`
13. `feat(db): add repository pattern with cursor pagination`
14. `feat(api): add service layer with tenant scoping and tier decorator`
15. `feat(api): implement /capabilities endpoint with env + workspace overlay`
16. `feat(db): add audit log SQLAlchemy listener + request middleware`
17. `feat(api): add GET /auth/me and workspace read endpoints`
18. `feat(api): add project + suite read endpoints with pagination`
19. `feat(api): add test case read endpoints with filters + executable per tier`
20. `feat(api): add requirement + traceability read endpoints`
21. `feat(api): add run, run-step, log, and artifact read endpoints`
22. `feat(api): add defect read endpoints + timeline`
23. `feat(api): add integration read endpoints with redacted secrets`
24. `feat(api): add document read endpoints`
25. `feat(api): add analytics read endpoints (kpis, pass-rate, coverage, flaky, heatmap, readiness)`
26. `feat(db): add public ID Postgres function + per-entity event listeners`
27. `feat(db): add Nusantara Retail seed script with 18 cases + 9 integrations`
28. `feat(shared): export OpenAPI snapshot + CI drift gate`
29. `feat(api): wire OpenTelemetry, Prometheus, structlog`
30. `feat(api): add per-audience rate limiting via slowapi + Redis`
31. `chore(release): cut v0.2.0-m1a candidate`

Thirty-one commits, one acceptance-criterion-equivalent each.
