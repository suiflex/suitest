# M1d — ZERO Manual TCM Writes + Defects + Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ZERO tier fully usable end-to-end — author/edit test cases with Monaco step.code editor, suite CRUD, drag-reorder steps via dnd-kit, soft-delete with undo, bulk operations, requirement linking, run trigger from UI, manual defect creation + rule-based auto-defect on run failure, full Jira/Linear/GitHub integration adapters (file external issue + sync status), Slack notifications, GitHub webhook trigger.

**Architecture:** POST/PATCH/DELETE endpoints follow same router/service/repo pattern as M1a. Frontend mutations via TanStack Query `useMutation` with optimistic updates + rollback. Step editor uses Monaco Editor (lazy-loaded) for code field, dnd-kit for reorder. Integrations adapter pattern: `IssueTrackerAdapter` interface implemented by JiraAdapter, LinearAdapter, GitHubAdapter. Defect auto-file uses rule-based categorizer (assertion message regex → category) since no LLM in ZERO. Webhook receiver validates HMAC.

**Tech Stack:** Same as previous milestones + `httpx` for vendor APIs, `pyjwt`/`itsdangerous` for HMAC, Monaco Editor (`@monaco-editor/react`), `@dnd-kit/core` + `@dnd-kit/sortable`, `sonner` for toasts, `react-hook-form` + `zod` resolver.

---

## Prerequisites

Before starting M1d, verify:

- **M0** complete — monorepo, Docker compose, FastAPI + Vite boot, FastAPI-Users auth wired, base migrations applied.
- **M1a** complete — read-only REST endpoints (`GET /test-cases`, `GET /suites`, `GET /runs`, `GET /defects`, `GET /requirements`, `GET /integrations`) shipped with workspace scoping, audit log helper, pagination, error envelope.
- **M1b** complete — read-only UI screens (Dashboard, Cases list/detail placeholder, Runs, Defects, Analytics, Traceability, Integrations grid, Docs) wired against M1a endpoints.
- **M1c** complete — ARQ runner picks queued runs, dispatches step-by-step to MCP via `packages/mcp/client`, persists `RunStep` rows with outcome + artifacts, streams `run.step.*` over WS. **Task 12 of M1c** declared an unimplemented callback hook `on_run_step_failed(run_step)` — M1d wires the auto-defect filer to that hook.
- **M1c task 6** registered `playwright-mcp`, `api-http-mcp`, `postgres-mcp` providers in the bundled registry with health probes.

If any prerequisite is missing, stop and complete that milestone first.

---

## Conventions for this plan

- **TDD always.** Each backend task: (1) write failing pytest, (2) implement, (3) green test, (4) refactor.
- **Frontend mutations** use TanStack Query `useMutation` with `onMutate` (optimistic snapshot), `onError` (rollback), `onSettled` (invalidate). Pair with sonner toast for user feedback.
- **Forms** use React Hook Form + `@hookform/resolvers/zod`. Schema lives in `packages/shared/src/schemas/*.ts` (Zod) — generate matching Pydantic in `packages/shared/suitest_shared/schemas/*.py` manually until codegen lands in M4.
- **Capability gate** every mutation that touches AI-only features via `Depends(require_tier(...))`. ZERO-tier features (manual TCM, manual defect, integration CRUD, webhook receivers, rule-based auto-file) do **not** require gating but do require auth.
- **Audit log** every mutation. Wrap each service method that writes in `audit_log.record(workspace_id, user_id, action, resource_type, resource_id, metadata)`.
- **Soft-delete** semantics: cases/suites/projects/requirements set `deleted_at`, retained 30 days, hard-deleted by background job (out of M1d scope — just store the column). Bulk operations + undo toast both rely on this.
- **Atomic step replacement** for `PATCH /test-cases/:id/steps`: open a transaction, delete existing `test_steps` rows for the case, insert new ones (re-numbered 1..N), commit. Validate the whole list per tier rules before touching DB.
- **No barrel files.** Import direct (`from suitest_api.services.test_case_service import TestCaseService` not `from suitest_api.services import TestCaseService`).
- **No `Any` in Python.** Use `TypedDict`, `Protocol`, or specific Pydantic models. No `as any` in TS.
- Each numbered task ends with a `git commit` — use conventional commits referencing the M1 acceptance criterion (`feat(api): add POST /test-cases (Closes #M1-12)`).

---

## Task 1: Test Case CRUD endpoints

### Sub-task 1a — POST /test-cases (create)

- [ ] **1a.1** Write Pydantic schemas in `packages/shared/suitest_shared/schemas/test_case.py`:
  - `TestStepCreate(BaseModel)` — `order: int >=1`, `action: str (min_len=1, max_len=500)`, `expected: str (min_len=0, max_len=2000)`, `code: str | None`, `data: dict | None`, `mcp_provider: str`, `target_kind: TargetKind`.
  - `TestCaseCreate(BaseModel)` — `suite_id: str`, `name: str (min_len=1, max_len=255)`, `description: str | None`, `preconditions: str | None`, `source: CaseSource = MANUAL`, `priority: Priority = P2`, `owner_id: str | None`, `tags: list[str] = []`, `steps: list[TestStepCreate]`.
  - `TestCaseRead(BaseModel)` — full case + steps + computed `executable: bool` per step + `tags: list[str]` + `public_id`.
- [ ] **1a.2** Pytest in `apps/api/tests/test_cases_create.py` — write before implementing:
  - Happy path: ZERO workspace, all steps have `code` → 201, response shape matches `TestCaseRead`, `public_id` matches `^TC-\d+$`, `executable=true` for every step.
  - 400 on empty `name`.
  - 400 on `steps=[]`.
  - 400 `STEPS_REQUIRE_CODE_IN_ZERO_LLM` when one step missing `code` and workspace has `strict_zero_validation=true` (default). Error body must contain `stepIndex`.
  - 200 (accepted) when one step missing `code` AND workspace `strict_zero_validation=false` AND tier=ZERO; `executable` flag on that step is `false` in response.
  - 200 (accepted) for action-only step in LOCAL/CLOUD tier; `executable=true`.
  - 404 `MCP_PROVIDER_NOT_REGISTERED` when `mcp_provider` not in workspace registry. Use fixture `unregistered_mcp_workspace`.
  - 403 when calling user is `VIEWER` role (only QA/ADMIN/OWNER may write).
  - 401 unauthenticated.
- [ ] **1a.3** Validator implementation in `apps/api/src/suitest_api/services/test_case_validator.py`:
  - `validate_steps(steps: list[TestStepCreate], tier: Tier, workspace_settings: WorkspaceSettings, registered_mcp_names: set[str]) -> None`.
  - Iterate steps. For each: ensure `mcp_provider in registered_mcp_names` else raise `McpProviderNotRegistered(name)`.
  - If `tier == ZERO and workspace_settings.strict_zero_validation` and `step.code is None`: raise `StepsRequireCodeInZeroLlm(step_index=i)`.
  - Numbering: re-number `order` to `i+1` regardless of input (idempotent).
- [ ] **1a.4** Service method `TestCaseService.create(workspace_id, user_id, payload) -> TestCase`:
  - Begin transaction.
  - Fetch workspace settings + tier (via `CapabilityRepo.get_tier(workspace_id)` cached in request scope).
  - Fetch registered MCP names via `McpProviderRepo.list_names(workspace_id)`.
  - Run `validate_steps`.
  - Call DB function `nextval('test_case_public_seq')` → format `TC-{n}` (function & sequence created in initial migration; if not present add migration `1Xxx_add_public_id_sequences.py`).
  - Insert `TestCase` row + `TestStep` rows + `CaseTag` rows.
  - Append audit log row (`action=test_case.created`, metadata={ stepCount, source }).
  - Commit; emit WS event `case.created` to room `workspace:{workspaceId}`.
  - Return ORM model converted to domain `TestCase`.
- [ ] **1a.5** Router handler in `apps/api/src/suitest_api/routers/test_cases.py`:
  ```python
  @router.post("", response_model=TestCaseRead, status_code=201)
  async def create_case(
      payload: TestCaseCreate,
      svc: Annotated[TestCaseService, Depends(get_test_case_service)],
      ctx: Annotated[RequestContext, Depends(require_role({Role.QA, Role.ADMIN, Role.OWNER}))],
  ) -> TestCaseRead:
      case = await svc.create(ctx.workspace_id, ctx.user_id, payload)
      return TestCaseRead.model_validate(case)
  ```
- [ ] **1a.6** Map domain exceptions to HTTP via existing `apps/api/src/suitest_api/errors.py`:
  - `StepsRequireCodeInZeroLlm` → 400 with `code=STEPS_REQUIRE_CODE_IN_ZERO_LLM`, `details.stepIndex`.
  - `McpProviderNotRegistered` → 404 with `code=MCP_PROVIDER_NOT_REGISTERED`, `details.name`.
- [ ] **1a.7** Run `pytest apps/api/tests/test_cases_create.py -x`. All green.
- [ ] **1a.8** Sanity-check the `public_id` sequence:
  - Verify the migration that creates `test_case_public_seq` is idempotent (`CREATE SEQUENCE IF NOT EXISTS`).
  - Add concurrency test: two parallel POST requests → both succeed with distinct `public_id` values.
  - Audit log includes the assigned `public_id` in metadata so post-hoc forensics can resolve `TC-N` → caseId.
- [ ] **1a.9** **Workspace scoping defensive layer:**
  - The router pulls `workspace_id` from the `X-Workspace-Id` header (or path segment); the service NEVER trusts a `suite_id` payload without re-checking that the suite belongs to that workspace.
  - Add `_assert_suite_in_workspace(suite_id, workspace_id)` helper invoked at the start of `create`. Returns 404 (not 403) on mismatch to avoid tenant enumeration.
  - Pytest: cross-tenant POST with another workspace's suite_id → 404.
- [ ] **1a.10** **Tag normalization:** trim whitespace, lowercase, max-len 64, dedup, max 20 tags per case. Test covers each rule.

### Sub-task 1b — PATCH /test-cases/:id (update metadata)

- [ ] **1b.1** Pydantic `TestCaseUpdate(BaseModel)` — all fields optional: `name`, `description`, `preconditions`, `priority`, `owner_id`, `status`, `tags`. **Note: `tags` replace semantics (full set).** Steps are NOT updatable via this endpoint (use 1c).
- [ ] **1b.2** Pytest `apps/api/tests/test_cases_update_metadata.py`:
  - Happy path: update `name` + `priority` → 200, returns updated `TestCaseRead`.
  - Updating `tags=["smoke", "p0"]` → response tags list equals input (insertion order preserved).
  - Updating `tags=[]` → existing tags removed.
  - 404 on unknown case id.
  - 403 cross-workspace access.
  - 422 on `priority` not in enum.
- [ ] **1b.3** Service method `TestCaseService.update_metadata(case_id, workspace_id, user_id, patch) -> TestCase`:
  - Fetch + check workspace match (raise `ResourceNotFound` if mismatched — never leak cross-tenant 403).
  - Apply patch via `setattr` for non-tag fields.
  - For tags: delete-then-insert in transaction.
  - Audit log `test_case.updated` with `changed_fields` list.
  - Emit `case.updated` WS event.
- [ ] **1b.4** Router PATCH handler.
- [ ] **1b.5** Test green.

### Sub-task 1c — PATCH /test-cases/:id/steps (atomic replace)

- [ ] **1c.1** Pydantic `TestStepsReplace(BaseModel)` — `steps: list[TestStepCreate] (min_length=1)`.
- [ ] **1c.2** Pytest `apps/api/tests/test_cases_replace_steps.py`:
  - Happy path: replace 3-step case with 2-step list → 200, `GET /test-cases/:id` returns exactly those 2 steps with re-numbered `order=1,2`.
  - Atomic rollback: simulate `IntegrityError` on second insert via mocked repo → response 500, original 3 steps still present in DB.
  - 400 step missing `code` in ZERO strict.
  - 400 empty list (`steps=[]`).
  - 404 unknown case id.
  - 200 for LOCAL/CLOUD with action-only step.
  - WS event `case.steps.replaced` emitted exactly once on success.
- [ ] **1c.3** Service method `TestCaseService.replace_steps(case_id, workspace_id, user_id, payload) -> TestCase`:
  - Open transaction.
  - Lock case row `SELECT ... FOR UPDATE`.
  - Validate via `validate_steps`.
  - Delete all rows `WHERE case_id = :id` from `test_steps`.
  - Bulk insert new rows with `order = idx + 1`.
  - Update `test_cases.updated_at = NOW()`.
  - Commit; audit `test_case.steps_replaced`; emit WS.
- [ ] **1c.4** Router handler `@router.patch("/{case_id}/steps")`.
- [ ] **1c.5** Test green.

### Sub-task 1d — POST /test-cases/:id/steps (append)

- [ ] **1d.1** Pydantic `TestStepAppend = TestStepCreate` (order ignored — server assigns `max(order)+1`).
- [ ] **1d.2** Pytest `apps/api/tests/test_cases_append_step.py`:
  - Happy path: case has 2 steps → append → 201, response is the new step with `order=3`.
  - 400 in ZERO strict without `code`.
  - 404 case not found.
  - 404 unknown `mcp_provider`.
  - Concurrent appends: 2 parallel requests → both succeed, orders 3 and 4 (no collision). Use `SELECT MAX(order) ... FOR UPDATE` on parent case row.
- [ ] **1d.3** Service `TestCaseService.append_step(case_id, ws_id, user_id, payload) -> TestStep`.
- [ ] **1d.4** Router. Test green.

### Sub-task 1e — DELETE /test-cases/:id (soft delete)

- [ ] **1e.1** Pytest `apps/api/tests/test_cases_delete.py`:
  - Happy path: 204 No Content. `GET /test-cases/:id` returns 404 afterwards. `GET /test-cases/:id?includeDeleted=true` returns row with `deletedAt` set (admin-only query param).
  - Idempotent: second DELETE returns 404 (already deleted).
  - 404 unknown.
  - Cross-workspace: 404.
  - Linked defects keep their `test_case_id` reference (not nulled — historic accuracy).
- [ ] **1e.2** Add `POST /test-cases/:id/restore` for undo. Pytest:
  - Happy path: restore returns 200 + full case. `GET /test-cases/:id` works again.
  - 410 Gone after retention window (30 days — for M1d we just set the response; hard-delete job out of scope).
  - 404 if never deleted.
- [ ] **1e.3** Service `TestCaseService.soft_delete(case_id, ws_id, user_id)` sets `deleted_at = NOW()`, audit `test_case.deleted`. `restore(case_id, ...)` sets `deleted_at = NULL`, audit `test_case.restored`.
- [ ] **1e.4** Update list endpoint `GET /test-cases` filter: default excludes `deleted_at IS NOT NULL`. Pytest covers this case.
- [ ] **1e.5** Test green.

### Sub-task 1f — POST /test-cases/:id/duplicate

- [ ] **1f.1** Pydantic `TestCaseDuplicate(BaseModel)` — `name_suffix: str = " (copy)"`, `target_suite_id: str | None`.
- [ ] **1f.2** Pytest `apps/api/tests/test_cases_duplicate.py`:
  - Happy path: case with 3 steps + 2 tags → 201, new case has new `public_id`, name = old name + suffix, same 3 steps with new step ids + new tags rows (duplicated values).
  - `target_suite_id` provided → new case lives in target suite.
  - `target_suite_id` cross-workspace → 404.
  - Duplicate inherits `source=MANUAL` (not the original source — duplicates are manual creations).
  - Duplicates a deleted case → 404.
- [ ] **1f.3** Service `TestCaseService.duplicate(case_id, ws_id, user_id, payload) -> TestCase`.
- [ ] **1f.4** Router. Test green.

### Sub-task 1g — POST /test-cases/:id/run (ad-hoc run shortcut)

- [ ] **1g.1** Pydantic `AdHocRunCreate(BaseModel)` — `env: str = "staging"`, `branch: str | None`, `commit_sha: str | None`, `mcp_routing_override: dict[str, str] | None`.
- [ ] **1g.2** Pytest `apps/api/tests/test_cases_run.py`:
  - Happy path ZERO tier with all-code steps: 202 Accepted, response `{ runId, publicId, statusUrl, wsRoom }`. ARQ job enqueued (assert via mocked `arq_pool.enqueue_job` call args).
  - Action-only step in ZERO: 400 `STEPS_REQUIRE_CODE_IN_ZERO_LLM` (pre-flight check before enqueuing).
  - Soft-deleted case: 404.
  - 404 unknown case.
  - Audit log `run.created` recorded.
  - Run row has `trigger=MANUAL`, `tier_at_runtime=ZERO` (snapshot from current workspace), name `"Ad-hoc: {case.name}"`.
- [ ] **1g.3** Service `TestCaseService.enqueue_ad_hoc_run(case_id, ws_id, user_id, payload) -> Run`:
  - Pre-flight: load case + steps, run `validate_steps` again (defensive).
  - Delegate to existing `RunService.create(...)` (from M1c) with `selection={"type":"cases","ids":[case_id]}`.
  - Return `Run` row with WS room name.
- [ ] **1g.4** Router. Test green.
- [ ] **1g.5** **Commit** — `feat(api): test-case CRUD + ad-hoc run (Closes #M1-12 #M1-15)`.

---

## Task 2: Suite CRUD

- [ ] **2.1** Pydantic schemas in `packages/shared/suitest_shared/schemas/suite.py`:
  - `SuiteCreate` — `project_id`, `name`, `description`, optional `parent_id`.
  - `SuiteUpdate` — partial of above + `case_order: list[str] | None` (list of case ids in desired order; updates each case's `order_in_suite` column — add column in migration `1Xxx_add_suite_order.py` if not present).
- [ ] **2.2** Pytest `apps/api/tests/test_suites_crud.py`:
  - POST happy: returns 201 + `SuiteRead`.
  - PATCH rename: 200.
  - PATCH `case_order=["TC-1","TC-3","TC-2"]` → re-order persists; subsequent `GET /test-cases?suiteId=...&sort=order_in_suite` returns that order.
  - DELETE empty suite → 204.
  - DELETE non-empty without `confirmCascade=true` query → 409 `SUITE_HAS_CASES` with `caseCount`.
  - DELETE non-empty with `confirmCascade=true` → 204, all cases soft-deleted (cascade).
  - Cross-workspace operations: 404.
- [ ] **2.3** Service `SuiteService.create / update / reorder_cases / delete(cascade=bool)`.
- [ ] **2.4** Router. Test green.
- [ ] **2.5** **Commit** — `feat(api): suite CRUD with cascade-confirm + case reorder (Closes #M1-13)`.

---

## Task 3: Project CRUD

- [ ] **3.1** Pydantic `ProjectCreate / ProjectUpdate / ProjectRead` in `.../schemas/project.py`.
- [ ] **3.2** Pytest `apps/api/tests/test_projects_crud.py`:
  - POST happy: 201, slug auto-generated from name (lowercased, hyphenated, dedup-suffixed if collision).
  - PATCH name → 200.
  - DELETE empty project → 204.
  - DELETE non-empty → 409 unless `confirmCascade=true` (cascades to suites → cases → defects soft-delete).
  - Audit entries recorded.
  - 403 when caller is QA — projects are ADMIN/OWNER only.
- [ ] **3.3** Service `ProjectService.create / update / delete`.
- [ ] **3.4** Router with `Depends(require_role({Role.ADMIN, Role.OWNER}))`.
- [ ] **3.5** Test green.
- [ ] **3.6** **Commit** — `feat(api): project CRUD admin-gated (Closes #M1-13)`.

---

## Task 4: Requirement + Link CRUD

- [ ] **4.1** Pydantic in `.../schemas/requirement.py`:
  - `RequirementCreate` — `project_id`, `title`, `description`, `source` (free text), `external_url`.
  - `RequirementUpdate` — all optional.
  - `RequirementLinkCreate` — `case_id`.
- [ ] **4.2** Pytest `apps/api/tests/test_requirements_crud.py`:
  - POST requirement → 201, `public_id` matches `^REQ-\d+$`.
  - PATCH → 200.
  - DELETE → 204 (also deletes orphan links by cascade).
  - POST link → 201 + 409 on duplicate `(req_id, case_id)`.
  - DELETE link → 204.
  - Cross-workspace req-to-case link → 400 `CROSS_WORKSPACE_LINK`.
- [ ] **4.3** Service `RequirementService.create / update / delete / link / unlink`.
- [ ] **4.4** Router. Test green.
- [ ] **4.5** **Commit** — `feat(api): requirement CRUD + link CRUD (Closes #M1-24)`.

---

## Task 5: Defect manual creation + rule-based auto-file

### Sub-task 5a — Manual defect endpoints

- [ ] **5a.1** Pydantic in `.../schemas/defect.py`:
  - `DefectCreate` — `test_case_id`, `run_id`, `requirement_id`, `title (required)`, `description`, `severity` (default `MEDIUM`), `component`, `assignee_id`.
  - `DefectUpdate` — `status`, `assignee_id`, `severity`, `component`, `description`.
  - `DefectRead` — full row + linked `external_issues: list[ExternalIssueRead]`.
- [ ] **5a.2** Pytest `apps/api/tests/test_defects_manual.py`:
  - POST manual: 201, `public_id` matches `^SUIT-\d+$`, `created_by` matches caller user id, `agent_diagnosis_kind=MANUAL_TRIAGE` default, `status=OPEN`.
  - PATCH `status=RESOLVED` → 200, `resolved_at` set to NOW.
  - PATCH `status=OPEN` after RESOLVED → 200, `resolved_at` cleared.
  - 404 unknown.
- [ ] **5a.3** POST `/defects/:id/sync-external` endpoint:
  - Resolves linked `external_issues` rows, calls per-provider adapter `get_issue(ref)`, updates local `status` if external status mapped to a different local status (use mapping from §7/§8/§9 below).
  - Pytest: stub external adapter; assert local status updated.
- [ ] **5a.4** Service `DefectService.create_manual / update / sync_external`.
- [ ] **5a.5** Router.
- [ ] **5a.6** Test green.

### Sub-task 5b — Rule-based auto-defect filer

- [ ] **5b.1** Pydantic in `.../schemas/defect.py`:
  - `AutoDefectInput(BaseModel)` — `run_step_id`, `case_id`, `run_id`, `error_message: str`, `stack_trace: str | None`, `case_priority: Priority`, `case_name: str`, `step_order: int`.
- [ ] **5b.2** Implement `DefectAutoFiler` in `apps/api/src/suitest_api/services/defect_auto_filer.py`:

  ```python
  import re
  from dataclasses import dataclass
  from packages.shared.suitest_shared.enums import DiagnosisKind, Priority, Severity

  _RULES: list[tuple[re.Pattern[str], DiagnosisKind]] = [
      # ordering matters — earlier rules win
      (re.compile(r"AssertionError|expect\(.*\)\.to", re.IGNORECASE), DiagnosisKind.REGRESSION),
      (re.compile(r"expected .* but (got|received|found) ", re.IGNORECASE), DiagnosisKind.SPEC_DRIFT),
      (re.compile(r"\bTimeoutError\b|timed out (after|waiting)|exceeded \d+ ?ms", re.IGNORECASE), DiagnosisKind.FLAKE),
      (re.compile(r"ECONNREFUSED|connection refused|ENOTFOUND|getaddrinfo", re.IGNORECASE), DiagnosisKind.INFRA),
      (re.compile(r"5\d\d (Internal Server Error|Bad Gateway|Service Unavailable|Gateway Timeout)"), DiagnosisKind.INFRA),
  ]

  _SEVERITY_BY_PRIORITY: dict[Priority, Severity] = {
      Priority.P0: Severity.CRITICAL,
      Priority.P1: Severity.HIGH,
      Priority.P2: Severity.MEDIUM,
      Priority.P3: Severity.MEDIUM,  # P2 + P3 collapse to MEDIUM per spec
  }


  @dataclass(frozen=True)
  class CategorizedDefect:
      title: str
      severity: Severity
      diagnosis_kind: DiagnosisKind
      description: str
      stack_trace: str | None


  class DefectCategorizer:
      def categorize(self, inp: AutoDefectInput) -> CategorizedDefect:
          first_line = (inp.error_message or "").strip().splitlines()[0] if inp.error_message else "Unknown failure"
          kind = DiagnosisKind.MANUAL_TRIAGE
          for pattern, mapped in _RULES:
              if pattern.search(inp.error_message or "") or (inp.stack_trace and pattern.search(inp.stack_trace)):
                  kind = mapped
                  break
          severity = _SEVERITY_BY_PRIORITY.get(inp.case_priority, Severity.MEDIUM)
          title = f"Test {inp.case_name} failed at step {inp.step_order}: {first_line[:140]}"
          description = (
              f"Auto-filed by Suitest defect filer (rule-based; tier=ZERO).\n\n"
              f"**Run:** {inp.run_id}\n"
              f"**Case:** {inp.case_name}\n"
              f"**Step:** #{inp.step_order}\n"
              f"**Detected category:** {kind.value}\n\n"
              f"```\n{inp.error_message or '(no message)'}\n```"
          )
          return CategorizedDefect(
              title=title,
              severity=severity,
              diagnosis_kind=kind,
              description=description,
              stack_trace=inp.stack_trace,
          )


  class DefectAutoFiler:
      def __init__(
          self,
          defect_repo: DefectRepo,
          run_repo: RunRepo,
          categorizer: DefectCategorizer,
          arq_pool: ArqRedis,
          audit: AuditLog,
          ws_bus: WsBus,
      ) -> None: ...

      async def file_for_failed_step(self, run_step_id: str) -> Defect | None:
          # 1. fetch run_step, case, run, workspace
          # 2. if defect already exists for this (run_id, case_id) → return None (dedup)
          # 3. build AutoDefectInput from run_step + case + run
          # 4. categorize
          # 5. persist defect (created_by="system", agent_diagnosis_kind=kind)
          # 6. audit_log "defect.auto_filed"
          # 7. emit ws "defect.created" to workspace room
          # 8. enqueue arq job "file_external_issue" with defect_id (only if a tracker integration exists for workspace)
          # 9. enqueue arq job "send_slack_notification" with defect_id (only if slack integration exists)
          # 10. return Defect
  ```
- [ ] **5b.3** Pytest `apps/api/tests/test_defect_auto_filer.py`:
  - Rule REGRESSION: error="AssertionError: expected true to be false" → `diagnosis_kind=REGRESSION`.
  - Rule SPEC_DRIFT: error="expected 200 but got 404" — but note: the REGRESSION rule contains `expect(.*).to` not the bare word "expected"; SPEC_DRIFT rule wins for "expected ... but got" plain English. Verify the **second rule fires** because the first is more specific to assertion library syntax.
  - Rule FLAKE: error="TimeoutError: page.goto timed out after 30000ms" → `FLAKE`.
  - Rule INFRA (ECONNREFUSED): error="connect ECONNREFUSED 127.0.0.1:5432" → `INFRA`.
  - Rule INFRA (HTTP 5xx): error="503 Service Unavailable" → `INFRA`.
  - Fallback MANUAL_TRIAGE: error="something weird" → `MANUAL_TRIAGE`.
  - Severity heuristic: P0 case → CRITICAL, P1 → HIGH, P2 → MEDIUM, P3 → MEDIUM.
  - Title format: `"Test {name} failed at step {n}: {first_line[:140]}"`.
  - Dedup: second call with same `(run_id, case_id)` returns `None`, no new defect row created.
  - WS emit assertion: `ws_bus.emit.assert_called_once_with("workspace:<id>", "defect.created", ...)`.
  - External issue arq job enqueued **only** when a `JIRA` or `LINEAR` or `GITHUB` integration row exists for the workspace.
  - Slack arq job enqueued only when `SLACK` integration exists.
- [ ] **5b.4** Wire `DefectAutoFiler` into the runner's M1c callback hook. In `apps/runner/src/suitest_runner/handlers/step_handler.py`, modify the step-completion path:
  ```python
  if outcome == StepOutcome.FAIL:
      async with sessionmaker() as session:
          filer = DefectAutoFiler(...)  # built via runner DI
          await filer.file_for_failed_step(run_step.id)
  ```
  Update runner DI container in `apps/runner/src/suitest_runner/deps.py` to expose `DefectAutoFiler`.
- [ ] **5b.5** Integration test `apps/runner/tests/test_runner_auto_defect.py`:
  - End-to-end with real Postgres (testcontainers): seed workspace + case (1 step that asserts pg row count = 5 but actual = 3 → assertion fail), enqueue run, wait for completion, assert defect row exists with `diagnosis_kind=REGRESSION`, `agent_diagnosis_kind=REGRESSION`, severity matches case priority.
- [ ] **5b.6** Test green.
- [ ] **5b.7** **Commit** — `feat(defect): manual + rule-based auto-file (Closes #M1-21 #M1-23)`.

### Sub-task 5c — Dedup + retry semantics for auto-filer

- [ ] **5c.1** Define dedup key: `(workspace_id, run_id, case_id)` — at most one auto-filed defect per (run, case) pair. Re-running the runner on the same step (e.g. transient runner crash + retry) must not produce duplicate defects.
  - Implementation: add partial unique constraint `uq_defects_auto_dedup ON defects(run_id, test_case_id) WHERE created_by = 'system'`. Alembic migration `1Xxx_defects_auto_dedup.py`.
- [ ] **5c.2** Pytest:
  - Two calls of `DefectAutoFiler.file_for_failed_step(same_run_step_id)` → second returns `None`, only 1 row exists.
  - Manual defect on same run+case allowed (because `created_by != 'system'`) — partial index excludes manual defects.
- [ ] **5c.3** External-issue arq job retry:
  - Job `file_external_issue` uses ARQ's built-in retry (max 5, exponential backoff starting 5s).
  - On final failure, write `audit_log` entry `defect.external_filing_failed` and emit WS event `integration.error` with details. Defect stays local; user can manually click "Sync to tracker" later.
- [ ] **5c.4** Slack notification job similarly retries.
- [ ] **5c.5** Test green.

---

## Task 6: Integration adapter pattern

- [ ] **6.1** Create `apps/api/src/suitest_api/integrations/base.py`:

  ```python
  from typing import Protocol, runtime_checkable
  from dataclasses import dataclass
  from packages.shared.suitest_shared.enums import DefectStatus, Severity


  @dataclass(frozen=True)
  class ExternalIssueInput:
      title: str
      description: str
      severity: Severity
      labels: list[str]
      reporter_email: str | None = None


  @dataclass(frozen=True)
  class ExternalIssue:
      provider: str            # "jira" | "linear" | "github"
      external_id: str         # "PROJ-123" or "abc-def" or "42"
      external_url: str
      status: str              # raw provider status (mapped via _STATUS_MAP)
      title: str
      synced_at: datetime


  @runtime_checkable
  class IssueTrackerAdapter(Protocol):
      provider_name: str  # class attribute

      async def create_issue(self, ws_id: str, payload: ExternalIssueInput) -> ExternalIssue: ...
      async def update_issue(self, ws_id: str, external_id: str, patch: dict[str, object]) -> ExternalIssue: ...
      async def get_issue(self, ws_id: str, external_id: str) -> ExternalIssue: ...
      def map_external_status_to_defect_status(self, external_status: str) -> DefectStatus: ...
  ```
- [ ] **6.2** Create `apps/api/src/suitest_api/integrations/registry.py`:
  ```python
  class AdapterRegistry:
      def __init__(self) -> None:
          self._adapters: dict[str, IssueTrackerAdapter] = {}

      def register(self, adapter: IssueTrackerAdapter) -> None:
          self._adapters[adapter.provider_name] = adapter

      def get(self, provider: str) -> IssueTrackerAdapter:
          if provider not in self._adapters:
              raise UnknownAdapter(provider)
          return self._adapters[provider]

      def list_providers(self) -> list[str]:
          return list(self._adapters.keys())
  ```
- [ ] **6.3** Contract test `apps/api/tests/integrations/test_adapter_contract.py` — applies to all registered adapters:
  - Pytest fixture loops over `AdapterRegistry.list_providers()`. Each adapter must:
    - Have `provider_name: str` class attribute matching the registry key.
    - Successfully call `create_issue` with a stub HTTP layer (`respx` mock) — assert request URL/method/payload match expected.
    - Successfully call `get_issue` and parse response.
    - `map_external_status_to_defect_status` returns a valid `DefectStatus` for all known provider statuses.
- [ ] **6.4** Run contract test (currently no concrete adapters — should pass with 0 iterations).
- [ ] **6.5** **Commit** — `feat(integrations): adapter Protocol + registry (Closes #M1-22)`.

---

## Task 7: Jira Cloud adapter

- [ ] **7.1** OAuth 3LO setup:
  - Config env: `SUITEST_JIRA_CLIENT_ID`, `SUITEST_JIRA_CLIENT_SECRET`, `SUITEST_JIRA_REDIRECT_URI`.
  - Endpoint `GET /integrations/jira/connect` — redirects to `https://auth.atlassian.com/authorize?audience=api.atlassian.com&client_id=...&scope=offline_access%20read:jira-work%20write:jira-work%20read:me&redirect_uri=...&state=<csrf>&response_type=code&prompt=consent`.
  - Endpoint `GET /integrations/jira/callback?code=...&state=...` — exchanges code for `{access_token, refresh_token, expires_in}` via `POST https://auth.atlassian.com/oauth/token`. Fetches `accessible-resources` to get `cloudId`. Encrypts refresh_token via `packages.core.crypto.aes_gcm_encrypt`. Inserts `Integration` row kind=`JIRA` with config={cloudId, projectKey, baseUrl} and secrets_encrypted={refreshToken}.
- [ ] **7.2** Implement `apps/api/src/suitest_api/integrations/jira_adapter.py`:
  ```python
  class JiraAdapter:
      provider_name = "jira"

      def __init__(self, http: httpx.AsyncClient, repo: IntegrationRepo, crypto: CryptoService) -> None: ...

      async def _ensure_token(self, ws_id: str) -> tuple[str, str]:
          """Returns (access_token, cloud_id). Refreshes via stored refresh_token if expired."""
          ...

      async def create_issue(self, ws_id: str, payload: ExternalIssueInput) -> ExternalIssue:
          token, cloud_id = await self._ensure_token(ws_id)
          integration = await self.repo.get_by_kind(ws_id, "JIRA")
          project_key = integration.config["projectKey"]
          body = {
              "fields": {
                  "project": {"key": project_key},
                  "summary": payload.title[:255],
                  "description": {
                      "type": "doc", "version": 1,
                      "content": [{"type": "paragraph", "content": [{"type": "text", "text": payload.description}]}],
                  },
                  "issuetype": {"name": "Bug"},
                  "labels": payload.labels,
                  "priority": {"name": self._severity_to_priority(payload.severity)},
              }
          }
          resp = await self.http.post(
              f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue",
              json=body,
              headers={"Authorization": f"Bearer {token}"},
          )
          resp.raise_for_status()
          data = resp.json()
          # parse key, build URL, return ExternalIssue
          ...
  ```
  - Status mapping (`map_external_status_to_defect_status`):
    - `"To Do"`, `"Open"`, `"Backlog"` → `OPEN`
    - `"In Progress"`, `"In Review"` → `IN_PROGRESS`
    - `"Done"`, `"Resolved"` → `RESOLVED`
    - `"Closed"` → `CLOSED`
    - `"Won't Do"`, `"Cancelled"` → `WONT_FIX`
    - unknown → `OPEN` (safe default; log warning)
  - Severity → Jira priority name:
    - `CRITICAL` → "Highest"
    - `HIGH` → "High"
    - `MEDIUM` → "Medium"
    - `LOW` → "Low"
- [ ] **7.3** Pytest `apps/api/tests/integrations/test_jira_adapter.py` with `respx`:
  - `create_issue` happy path: mock `POST /rest/api/3/issue` → returns `{key:"PROJ-101", id:"10001"}` + mock `GET /rest/api/3/issue/PROJ-101` for url construction. Assert returned `ExternalIssue.external_id == "PROJ-101"`.
  - `_ensure_token` refresh flow: stored token expired → mock `POST https://auth.atlassian.com/oauth/token` → returns new access_token. Subsequent create succeeds.
  - 401 from Jira → adapter retries once after refresh; second 401 raises `IntegrationAuthError`.
  - Status mapping covers each enum value.
  - VCR cassette `tests/integrations/cassettes/jira/create_issue.yaml` for one full happy-path recording.
- [ ] **7.4** Register adapter at app startup: `apps/api/src/suitest_api/main.py` lifespan adds `registry.register(JiraAdapter(...))`.
- [ ] **7.5** Test green.
- [ ] **7.6** **Commit** — `feat(integrations): Jira Cloud adapter via OAuth 3LO (Closes #M1-22)`.

### Sub-task 7b — Jira webhook receiver (status sync back)

- [ ] **7b.1** Endpoint `POST /webhooks/jira` to receive issue update events.
  - Validate via JWT in the `Authorization: JWT ...` header — Jira signs with the shared secret of the Connect app (or for OAuth-based integration, validate via the `installation` claim).
  - Event types: `jira:issue_updated` — extract `issue.key` + `issue.fields.status.name`.
  - Look up local `external_issues` row by `(provider="jira", external_id=key)`.
  - Map status via `JiraAdapter.map_external_status_to_defect_status`. If mapped status differs from current local `defect.status`, update locally + audit `defect.status_synced_from_jira`.
- [ ] **7b.2** Pytest fixtures: signed payload, assert local defect status updated.
- [ ] **7b.3** Test green.
- [ ] **7b.4** **Commit** — `feat(webhooks): Jira issue status sync (Closes #M1-22)`.

---

## Task 8: Linear adapter

- [ ] **8.1** Auth: Linear Personal API Key (simpler than OAuth for v1). User pastes key in Settings → Integrations → Linear modal. Stored AES-GCM encrypted in `Integration.secrets_encrypted`.
- [ ] **8.2** Implement `apps/api/src/suitest_api/integrations/linear_adapter.py`:
  ```python
  class LinearAdapter:
      provider_name = "linear"

      async def create_issue(self, ws_id: str, payload: ExternalIssueInput) -> ExternalIssue:
          key = await self._get_api_key(ws_id)
          integration = await self.repo.get_by_kind(ws_id, "LINEAR")
          team_id = integration.config["teamId"]
          mutation = """
              mutation IssueCreate($input: IssueCreateInput!) {
                  issueCreate(input: $input) {
                      success
                      issue { id identifier url title state { name } }
                  }
              }
          """
          variables = {
              "input": {
                  "teamId": team_id,
                  "title": payload.title[:255],
                  "description": payload.description,
                  "priority": self._severity_to_priority(payload.severity),  # 0-4
                  "labelIds": [],
              }
          }
          resp = await self.http.post(
              "https://api.linear.app/graphql",
              json={"query": mutation, "variables": variables},
              headers={"Authorization": key, "Content-Type": "application/json"},
          )
          ...
  ```
  - Status mapping: state name `"Backlog"`/`"Todo"` → `OPEN`; `"In Progress"`/`"In Review"` → `IN_PROGRESS`; `"Done"` → `RESOLVED`; `"Cancelled"` → `WONT_FIX`.
  - Severity → priority: CRITICAL→1 (Urgent), HIGH→2 (High), MEDIUM→3 (Medium), LOW→4 (Low).
- [ ] **8.3** Pytest `apps/api/tests/integrations/test_linear_adapter.py` with `respx` + VCR cassette.
- [ ] **8.4** Register adapter.
- [ ] **8.5** Test green.
- [ ] **8.6** **Commit** — `feat(integrations): Linear GraphQL adapter (Closes #M1-22)`.

---

## Task 9: GitHub adapter (Issues)

- [ ] **9.1** GitHub App auth — installation token flow:
  - Config env: `SUITEST_GITHUB_APP_ID`, `SUITEST_GITHUB_APP_PRIVATE_KEY` (PEM, base64-encoded), `SUITEST_GITHUB_APP_NAME`.
  - On `Integration` connect, user supplies `{owner, repo, installationId}` (gleaned via app install link → callback).
  - `_get_installation_token(ws_id)` flow: build JWT signed with private key (10 min ttl) → exchange at `POST https://api.github.com/app/installations/{installationId}/access_tokens` → returns short-lived installation token (1h). Cache in memory keyed by installation id with 50-min expiry.
- [ ] **9.2** Implement `apps/api/src/suitest_api/integrations/github_adapter.py`:
  ```python
  class GitHubAdapter:
      provider_name = "github"

      async def create_issue(self, ws_id: str, payload: ExternalIssueInput) -> ExternalIssue:
          token = await self._get_installation_token(ws_id)
          integration = await self.repo.get_by_kind(ws_id, "GITHUB")
          owner = integration.config["owner"]
          repo = integration.config["repo"]
          body = {
              "title": payload.title[:255],
              "body": payload.description,
              "labels": payload.labels + [f"severity:{payload.severity.value.lower()}"],
          }
          resp = await self.http.post(
              f"https://api.github.com/repos/{owner}/{repo}/issues",
              json=body,
              headers={
                  "Authorization": f"token {token}",
                  "Accept": "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28",
              },
          )
          ...
  ```
  - Status mapping: `"open"` → `OPEN`; `"closed"` (with state_reason=`completed`) → `RESOLVED`; `"closed"` (state_reason=`not_planned`) → `WONT_FIX`.
- [ ] **9.3** Pytest `apps/api/tests/integrations/test_github_adapter.py`:
  - Installation token mint + caching (assert second call within 50min hits cache, no JWT minted).
  - `create_issue` happy path with respx.
  - Severity label added.
  - VCR cassette for one full create.
- [ ] **9.4** Register adapter.
- [ ] **9.5** Test green.
- [ ] **9.6** **Commit** — `feat(integrations): GitHub Issues adapter via GitHub App (Closes #M1-22)`.

---

## Task 10: Slack notification adapter

- [ ] **10.1** Use Incoming Webhook (POST to URL — no token needed at our end; user pastes webhook URL during Connect flow). Stored AES-GCM encrypted.
- [ ] **10.2** Implement `apps/api/src/suitest_api/integrations/slack_adapter.py`:
  ```python
  class SlackAdapter:
      provider_name = "slack"

      async def send_defect_notification(self, ws_id: str, defect: Defect, external_issue_url: str | None) -> None:
          webhook_url = await self._get_webhook_url(ws_id)
          color = {"CRITICAL": "#dc2626", "HIGH": "#f97316", "MEDIUM": "#facc15", "LOW": "#84cc16"}.get(defect.severity.value, "#737373")
          blocks = [
              {"type": "header", "text": {"type": "plain_text", "text": f":warning: {defect.public_id} — {defect.title[:140]}"}},
              {"type": "section", "fields": [
                  {"type": "mrkdwn", "text": f"*Severity*\n{defect.severity.value}"},
                  {"type": "mrkdwn", "text": f"*Category*\n{defect.agent_diagnosis_kind.value}"},
              ]},
              {"type": "section", "text": {"type": "mrkdwn", "text": f"```{(defect.description or '')[:1500]}```"}},
          ]
          if external_issue_url:
              blocks.append({"type": "actions", "elements": [
                  {"type": "button", "text": {"type": "plain_text", "text": "View in tracker"}, "url": external_issue_url},
              ]})
          payload = {"attachments": [{"color": color, "blocks": blocks}]}
          resp = await self.http.post(webhook_url, json=payload)
          resp.raise_for_status()
  ```
- [ ] **10.3** Pytest `apps/api/tests/integrations/test_slack_adapter.py`:
  - Mock webhook server via `respx`. Assert POST body has `attachments[0].color` matches severity, `blocks` includes header + fields + section + actions (when external URL present).
  - 4xx from Slack → raises `IntegrationDeliveryError`.
  - Smoke-test connection: a `test_connection(ws_id)` method posts a benign "Suitest test message" payload.
- [ ] **10.4** Wire to `DefectAutoFiler` arq job `send_slack_notification(defect_id)`:
  - Job loads defect, fetches Slack integration row (skip if none), calls `SlackAdapter.send_defect_notification(ws_id, defect, external_url=defect.external_issues[0].external_url if any else None)`.
- [ ] **10.5** Test green.
- [ ] **10.6** **Commit** — `feat(integrations): Slack incoming-webhook adapter for defect notifications (Closes #M1-27)`.

---

## Task 11: GitHub webhook receiver

- [ ] **11.1** Endpoint `POST /webhooks/github`:
  - Header `X-Hub-Signature-256: sha256=<hex>` — required.
  - Validate via HMAC: `hmac.new(secret.encode(), body_bytes, "sha256").hexdigest()` then constant-time compare. Secret per workspace stored in `Integration` row's `config.webhook_secret` (set at GitHub App install).
  - Header `X-GitHub-Event` selects event type. Handle: `push`, `pull_request` (action ∈ {opened, synchronize, reopened}), `ping` (return 200 immediately).
- [ ] **11.2** Pydantic in `.../schemas/webhooks_github.py`:
  - `GitHubPushEvent` — `repository.full_name`, `ref`, `after` (commit SHA), `sender.login`.
  - `GitHubPullRequestEvent` — `action`, `repository.full_name`, `pull_request.head.ref`, `pull_request.head.sha`, `pull_request.number`, `pull_request.user.login`.
- [ ] **11.3** Service `WebhookReceiver.on_github_event(headers, body) -> WebhookResult`:
  - Verify signature (using all GitHub integration rows — try each workspace's secret until one matches; if none match, 401).
  - Look up workspace + project via `repository.full_name` (config in integration row maps repo full_name → projectId).
  - For matching event: locate gating suite (project setting `gating_suite_id`) OR all suites with case-tag `smoke`.
  - Enqueue `Run` via `RunService.create(...)` with `trigger=CI_PUSH` (push) or `CI_PR` (PR), branch/commit from payload.
  - Return 202 Accepted with `{ runId, runUrl }`.
- [ ] **11.4** Pytest `apps/api/tests/webhooks/test_github_webhook.py`:
  - Load fixture `tests/webhooks/fixtures/github_push_main.json` + compute correct signature with test secret → 202, assert `RunService.create` called once with matching branch/sha.
  - Bad signature → 401 `INVALID_WEBHOOK_SIGNATURE`.
  - `ping` event → 200 with `{ pong: true }`, no run enqueued.
  - Unknown `repository.full_name` → 200 with `{ ignored: true, reason: "no_matching_workspace" }` (don't leak existence to attackers).
  - PR action=`closed` → 200 ignored (only handle opened/synchronize/reopened).
  - Race: two simultaneous pushes for same commit → only one Run enqueued (dedup via unique constraint on `(project_id, commit_sha, trigger)` partial idx WHERE created_at > NOW - 60s).
- [ ] **11.5** Migration: add partial unique index `ix_runs_dedup_recent` ON `runs (project_id, commit_sha, trigger) WHERE created_at > NOW() - INTERVAL '60 seconds'`. (Alembic migration `1Xxx_runs_dedup.py`.)
- [ ] **11.6** Test green.
- [ ] **11.7** **Commit** — `feat(webhooks): GitHub push/PR receiver with HMAC verification (Closes #M1-27)`.

### Sub-task 11b — Gating-suite selection logic

- [ ] **11b.1** Helper `_select_suites_for_trigger(project, trigger_kind) -> list[Suite]`:
  - If project setting `gating_suite_id` is set → return that single suite.
  - Otherwise, return all suites whose cases include at least one with tag `smoke`.
  - If still empty → return empty list; webhook receiver returns 200 with `{ ignored: true, reason: "no_gating_suite_configured" }` (no run created, but acknowledged).
- [ ] **11b.2** Pytest: project with explicit `gating_suite_id` selected; project with no gating but tagged smoke cases gets the smoke-only suite; project with neither returns `ignored` without error.
- [ ] **11b.3** Project schema: add `gating_suite_id: str | None` column. Migration `1Xxx_projects_gating_suite.py`. Pydantic `ProjectUpdate` exposes the field. UI for setting it added in Task 22 (workspace settings).

---

## Task 12: GitLab webhook (scaffolding)

- [ ] **12.1** Endpoint `POST /webhooks/gitlab`:
  - Header `X-Gitlab-Token` — compared constant-time against stored token in integration row.
  - Handle `Push Hook`, `Merge Request Hook` events.
- [ ] **12.2** Pydantic in `.../schemas/webhooks_gitlab.py` (minimal for these two event types).
- [ ] **12.3** Service method `WebhookReceiver.on_gitlab_event(headers, body)` — same enqueue path as GitHub.
- [ ] **12.4** Pytest `apps/api/tests/webhooks/test_gitlab_webhook.py`:
  - Push event with matching token → 202.
  - Bad token → 401.
  - MR event action=`open` → 202.
  - Unknown event type → 200 ignored.
- [ ] **12.5** Test green.
- [ ] **12.6** **Commit** — `feat(webhooks): GitLab push/MR scaffolding (Closes #M1-27)`.

---

## Task 13: Integration CRUD endpoints

- [ ] **13.1** Pydantic in `.../schemas/integration.py`:
  - `IntegrationCreate` — `kind: IntegrationKind`, `name: str`, `config: dict`, `secrets: dict`.
  - `IntegrationUpdate` — `name?`, `config?`, `secrets?` (partial; secrets fully replaced when provided).
  - `IntegrationRead` — `id, kind, name, config (sanitized — strip any keys also present in `secrets` form), status, lastSyncedAt`. **Never returns secret values.** Returns `connectedSince`, `lastSyncedAt`.
- [ ] **13.2** Pytest `apps/api/tests/test_integrations_crud.py`:
  - POST `kind=JIRA, secrets={refreshToken:"x"}` → 201, response has NO `refreshToken` field anywhere.
  - PATCH update config without secrets → existing secrets preserved.
  - PATCH with new secrets → old secrets replaced (verify via DB row inspection).
  - DELETE → 204; subsequent POST `/integrations/:id/test` → 404.
  - GET list → returns all rows for workspace, secrets always redacted.
  - 403 when role=`VIEWER` or `QA` — integrations are ADMIN/OWNER.
- [ ] **13.3** POST `/integrations/:id/test`:
  - Routes to adapter's `test_connection(ws_id)` method (defined on each `IssueTrackerAdapter` + `SlackAdapter`).
  - Returns `{ ok: bool, latencyMs: int, message: str, details?: dict }`.
- [ ] **13.4** POST `/integrations/:id/sync`:
  - Generic manual resync: for trackers, refreshes OAuth tokens + emits no defect change; for Slack, posts a "Suitest reconnect test" message.
  - Returns `{ ok: bool, syncedAt: datetime }`.
- [ ] **13.5** Service `IntegrationService.create / update / delete / test / sync`. Encrypt secrets via `crypto.aes_gcm_encrypt(json.dumps(secrets), workspace.encryption_key)` before storing.
- [ ] **13.6** Router with role gate.
- [ ] **13.7** Test green.
- [ ] **13.8** **Commit** — `feat(api): integration CRUD + test + sync (Closes #M1-22)`.

---

## Task 14: FE — Test case editor

- [ ] **14.1** Lift placeholder file `apps/web/src/routes/_app/cases/$caseId.tsx` (created in M1b) into a full edit-mode editor.
- [ ] **14.2** Zod schemas in `apps/web/src/lib/schemas/test-case.ts`:
  - `StepSchema` matches backend `TestStepCreate` minus `order`.
  - `CaseFormSchema = z.object({ name, description, preconditions, priority, ownerId, tags, steps: z.array(StepSchema).min(1) })`.
- [ ] **14.3** Build `CaseEditor` component (`apps/web/src/components/cases/CaseEditor.tsx`):
  - Wrap in `<form>` from `useForm({ resolver: zodResolver(CaseFormSchema), defaultValues })`.
  - Top section: case metadata fields (name, description, priority dropdown, owner picker, tags chip input).
  - Steps section: `useFieldArray({ name: "steps" })`. Render each step via `<StepRow>` (see 14.4).
  - "Add step" button (calls `append({ action: "", expected: "", code: null, mcpProvider: workspaceDefaultMcp, targetKind: "FE_WEB" })`).
  - Sticky bottom bar: "Save changes" primary button (disabled when `formState.isDirty=false`), "Discard" link.
- [ ] **14.4** Build `StepRow` component (`apps/web/src/components/cases/StepRow.tsx`):
  - Wrap in `<SortableItem id={step.id}>` from `@dnd-kit/sortable`.
  - Header row: grip handle (6-dot icon) + step number + collapse chevron + delete trash icon + duplicate icon.
  - Expanded body:
    - `action` — single-line `<Input>` bound via `register(\`steps.${idx}.action\`)`.
    - `expected` — multi-line `<Textarea>` (mono font).
    - `code` — **lazy-loaded** `<MonacoCodeEditor>` (see 14.5).
    - `mcpProvider` — `<Select>` populated from TanStack Query `useMcpProviders()` filtered by `targetKind`.
    - `targetKind` — `<Select>` over enum.
    - Executable indicator: small badge — green check if has code, red "Needs code" if no code in ZERO strict, gray "Action-only" otherwise.
- [ ] **14.5** Monaco wrapper `apps/web/src/components/cases/MonacoCodeEditor.tsx`:
  - `const Monaco = lazy(() => import("@monaco-editor/react"));` — gated in `<Suspense fallback={<TextareaPlaceholder />}>`.
  - Theme = `vs-dark`; language detected from mcpProvider (`api-http-mcp` → `typescript`, `postgres-mcp` → `sql`, default `typescript`).
  - Height auto-grows up to 240px (`automaticLayout: true`, `scrollBeyondLastLine: false`).
  - On blur → call `formatOnBlur` (Monaco's `editor.action.formatDocument`).
- [ ] **14.6** Dnd-kit wiring:
  - `<DndContext onDragEnd={handleDragEnd}>` wraps the step list.
  - `<SortableContext items={steps.map(s => s.id)} strategy={verticalListSortingStrategy}>`.
  - `handleDragEnd(event)`:
    ```ts
    if (event.over && event.active.id !== event.over.id) {
      const oldIdx = steps.findIndex(s => s.id === event.active.id);
      const newIdx = steps.findIndex(s => s.id === event.over.id);
      move(oldIdx, newIdx);  // useFieldArray's move
      setDirty(true);
    }
    ```
- [ ] **14.7** Save flow:
  - `const replaceSteps = useMutation({ mutationFn: (data) => api.patch(\`/test-cases/\${caseId}/steps\`, { steps: data.steps }), onMutate, onError, onSettled })`.
  - `const updateMeta = useMutation({ mutationFn: ... PATCH /test-cases/:id })`.
  - `onSubmit`: call both in parallel via `Promise.all`. On success, `toast.success("Saved")`. On error, `toast.error(<message from API>)` + rollback via `onError`.
- [ ] **14.8** Add unsaved-changes guard: `useBlocker` from TanStack Router → confirm dialog when navigating away with `formState.isDirty=true`.
- [ ] **14.9** Vitest `apps/web/src/components/cases/CaseEditor.test.tsx`:
  - Renders form populated from props.
  - "Add step" appends a new step row (assert via `screen.getAllByTestId("step-row").length`).
  - Dnd reorder: simulate `<DndContext>` `onDragEnd` with mock event → assert step order array changed; "Save" enabled.
  - Monaco lazy: `vi.mock("@monaco-editor/react", () => ({ default: () => <div data-testid="monaco-stub" /> }))`. Initial render shows `<TextareaPlaceholder>` from Suspense fallback; after promise resolves, monaco-stub is visible.
  - Save mutation: mock `api.patch`; click "Save"; assert PATCH `/test-cases/:id/steps` called with correct payload (steps array).
  - Save debounce: rapid clicks fire only once within 300ms window (verify via `vi.useFakeTimers`).
  - "Discard" click + unsaved → confirm dialog → on confirm, form resets to original `defaultValues`.
- [ ] **14.10** Test green.
- [ ] **14.11** **Commit** — `feat(web): test case editor with Monaco + dnd-kit reorder (Closes #M1-12 #M1-14)`.

### Sub-task 14b — Editor edge cases & UX polish

- [ ] **14b.1** Keyboard shortcut `Cmd+S` (Mac) / `Ctrl+S` (Win) → save. Implement via `useHotkeys('mod+s', handleSubmit, { preventDefault: true })` from `react-hotkeys-hook`.
- [ ] **14b.2** Empty step name placeholder: when `action` is empty, show muted placeholder "Describe what this step does..." inside the input.
- [ ] **14b.3** Drag-handle accessibility:
  - Each grip icon has `role="button"`, `aria-label="Drag to reorder step {n}"`.
  - Arrow-up/arrow-down keyboard reorder when handle is focused (dnd-kit's `useSortable` exposes keyboard sensor).
  - Vitest: focus handle, press ArrowDown → step index decrements (or appropriate side), `move()` called.
- [ ] **14b.4** Monaco editor a11y:
  - Set `options.accessibilitySupport: "on"`.
  - Label via `aria-label={\`Code for step \${n}\`}`.
- [ ] **14b.5** Saving state UX:
  - Button shows "Saving..." during mutation.
  - Inline conflict detection: if `PATCH /test-cases/:id/steps` returns 409 `CONCURRENT_MODIFICATION` (another user saved meanwhile — tracked via `updated_at` precondition header `If-Unmodified-Since`), show toast "Case changed by {user}. Refresh?" with "Reload" button that refetches.
  - Backend: add `If-Unmodified-Since` precondition support on PATCH endpoints. Pytest: client A saves at t1, client B saves at t0 with stale `If-Unmodified-Since` → 409. Update Task 1c.5 to cover this assertion.
- [ ] **14b.6** Step duplicate icon (next to trash): calls `useFieldArray.insert(idx+1, { ...steps[idx], id: nanoid(), action: steps[idx].action + " (copy)" })`. Test green.

---

## Task 15: FE — Generate (placeholder)

- [ ] **15.1** On Cases list page (`apps/web/src/routes/_app/cases/index.tsx`), replace existing "New" button with split-button:
  - Main button label "New test case" → opens `<ManualCreateModal>` (see 15.2).
  - Dropdown chevron menu items:
    - "Manual create" → opens `<ManualCreateModal>`.
    - "Recorder" — disabled with `<DisabledTooltip reason="Available in M2">`.
    - "OpenAPI" — disabled with `<DisabledTooltip reason="Available in M2">`.
    - "Crawler" — disabled with `<DisabledTooltip reason="Available in M2">`.
    - "Generate with AI" — disabled (M3) with `<DisabledTooltip reason="Available in M3 — configure LLM first">`.
- [ ] **15.2** `<ManualCreateModal>` component:
  - shadcn `<Dialog>`.
  - RHF + Zod (`name (required, max 255)`, `suiteId (required)`, `priority (default P2)`, `description (optional)`, initial step with `action + expected + mcpProvider + code` — code required when ZERO strict).
  - On submit: `POST /test-cases` → on 201, close modal, navigate to `/cases/{newId}` (full editor), toast success.
  - On 400 STEPS_REQUIRE_CODE_IN_ZERO_LLM → inline error on code field with link "Go to Settings → LLM to enable action-only steps".
- [ ] **15.3** Vitest `apps/web/src/components/cases/SplitGenerateButton.test.tsx`:
  - All disabled items render with tooltip (assert role="tooltip" appears on hover via `userEvent.hover`).
  - Clicking "Manual create" opens modal.
  - Modal submit successful → mutation called with correct shape.
  - Modal validates required fields (assert `screen.getByText(/name is required/i)` on empty submit).
- [ ] **15.4** Test green.
- [ ] **15.5** **Commit** — `feat(web): split generate button + manual create modal (Closes #M1-12)`.

---

## Task 16: FE — Run trigger UI

- [ ] **16.1** Case detail page actions toolbar — add "Run now" primary button.
  - On click → `useMutation({ mutationFn: () => api.post(\`/test-cases/\${caseId}/run\`, { env: "staging" }) })`.
  - On success (202): `toast.success(<>Run started — <Link to={\`/runs/\${runId}\`}>View run</Link></>)`.
  - On error STEPS_REQUIRE_CODE_IN_ZERO_LLM → `toast.error(<>Step \${stepIndex} needs code. <Link to={\`/cases/\${caseId}\`}>Edit</Link></>)`.
  - Disable button while mutation pending (`isPending` → spinner).
- [ ] **16.2** Dashboard "Run gating suite" button (placeholder in M1b):
  - Wire to `<Dialog>` that shows suite picker (multi-select). On submit → `POST /runs` with `selection={type:"suite",ids:[...]}`.
  - Show estimated duration + case count below the picker.
  - Same success/error toast pattern.
- [ ] **16.3** Vitest `apps/web/src/routes/_app/cases/$caseId.test.tsx` (extends from Task 14 test):
  - Click "Run now" → mutation fires, success toast renders link to run.
  - Error STEPS_REQUIRE_CODE_IN_ZERO_LLM → error toast with edit link.
- [ ] **16.4** Test green.
- [ ] **16.5** **Commit** — `feat(web): run-now + gating-suite trigger UI (Closes #M1-20)`.

---

## Task 17: FE — Defect detail card

- [ ] **17.1** Lift defects page (placeholder in M1b) — `apps/web/src/routes/_app/defects.tsx`:
  - Cards layout (per UI_SPEC §3.4) — each card from M1b read-only, now interactive.
- [ ] **17.2** Per-card interactions:
  - Status dropdown (OPEN / IN_PROGRESS / RESOLVED / CLOSED / WONT_FIX) — `PATCH /defects/:id { status }`. Optimistic update.
  - Assignee combo box — search users in workspace via `GET /workspaces/:id/members?q=`, select one → PATCH `{ assigneeId }`.
  - Severity edit — inline dropdown.
  - "Sync to tracker" button — calls `POST /defects/:id/sync-external`. Show last sync time below button.
  - Linked items (test case, run, requirement) — clickable `<Link>` to their detail routes.
- [ ] **17.3** Filter bar at page top: status filter chips, severity chips, assignee filter, "auto-filed only" toggle (filters where `agent_diagnosis_kind != MANUAL_TRIAGE OR created_by = "system"`).
- [ ] **17.4** Vitest `apps/web/src/routes/_app/defects.test.tsx`:
  - Status change PATCHes correctly, optimistic update visible immediately.
  - On PATCH error → rollback to previous status.
  - Filter chips drop URL query param + refetch.
  - "Sync to tracker" button calls `POST /defects/:id/sync-external` and refreshes external_issues list.
- [ ] **17.5** Test green.
- [ ] **17.6** **Commit** — `feat(web): defect detail interactions + filters (Closes #M1-23)`.

---

## Task 18: FE — Integrations CRUD UI

- [ ] **18.1** Lift integrations page (`apps/web/src/routes/_app/integrations.tsx`) — convert from grid-of-static-cards to live data + actions.
- [ ] **18.2** Per integration card:
  - Status pill: green "connected" / red "error" / gray "off".
  - If not connected: "Connect" button.
    - Jira → window redirect to `/api/v1/integrations/jira/connect`.
    - GitHub → window redirect to `/api/v1/integrations/github/connect` (GitHub App install URL).
    - Linear → modal with API key input field + team picker (fetched after key entered via Linear's `viewer { id }` query).
    - Slack → modal with webhook URL input + channel name display.
  - If connected: "Configure" button (opens settings modal) + status line "Connected since {date}".
  - "Disconnect" button → confirm dialog ("Remove this integration? Existing external issues stay; new auto-files won't be sent.") → DELETE.
- [ ] **18.3** Add "Test connection" button in each Configure modal → `POST /integrations/:id/test` → show result inline.
- [ ] **18.4** Add link "Set as default tracker for new defects" toggle (one tracker per workspace).
- [ ] **18.5** Vitest `apps/web/src/routes/_app/integrations.test.tsx`:
  - Click "Connect Jira" → window.location.assign called with expected URL.
  - Linear modal flow: enter key → "Test" button calls `/integrations/:id/test`, shows success.
  - Disconnect with confirm → DELETE called, card flips to "Connect" state.
  - "Test connection" failure shows error message.
- [ ] **18.6** Test green.
- [ ] **18.7** **Commit** — `feat(web): integrations CRUD UI with connect/configure/disconnect (Closes #M1-22 #M1-27)`.

### Sub-task 18b — OAuth callback UX

- [ ] **18b.1** Callback route `apps/web/src/routes/_app/integrations/oauth-callback.tsx`:
  - Parses query params: `?provider=jira&status=ok` or `?provider=jira&status=error&reason=...`.
  - On success: toast "Connected to Jira", redirect to `/integrations`.
  - On error: toast with reason; redirect with error query so the originating card highlights red.
- [ ] **18b.2** Backend callback handlers (`/integrations/jira/callback`, `/integrations/github/callback`) issue a 302 redirect to this frontend route with appropriate status.
- [ ] **18b.3** Vitest: render the callback route with mocked query → assert toast + nav.

---

## Task 19: FE — Bulk operations on cases

- [ ] **19.1** Add multi-select column to cases list (tree view from M1b — extend with checkbox per case + "Select all" header checkbox).
- [ ] **19.2** When ≥1 case selected, sticky action bar appears at top of list:
  - "Delete (N)" → bulk DELETE `/test-cases/bulk` (new endpoint — add Task 19.3).
  - "Move to suite" → opens suite picker → bulk PATCH `/test-cases/bulk { ids, suiteId }`.
  - "Change priority" → enum picker → bulk PATCH `{ ids, priority }`.
  - "Add tag" → tag input → bulk PATCH `{ ids, addTags: [...] }`.
  - "Clear selection" → resets.
- [ ] **19.3** Backend bulk endpoint `POST /test-cases/bulk-update`:
  - Body: `{ ids: string[], patch: { suiteId?, priority?, addTags?, removeTags? } }` OR `{ ids: string[], action: "delete" }`.
  - Pytest `apps/api/tests/test_cases_bulk.py`:
    - Bulk delete 3 cases → 200 `{ updated: 3 }`, all soft-deleted.
    - Bulk move 5 cases to suite → 200, verify each row's `suite_id` changed.
    - Bulk add tag → cases already having the tag remain idempotent (no duplicate row), new tag inserts ok.
    - Mixed-workspace ids → 403 with details about the offending ids.
    - Limit: max 100 ids per call → 400 `BULK_LIMIT_EXCEEDED` for 101.
- [ ] **19.4** Service `TestCaseService.bulk_update(ws_id, user_id, payload)`. Single transaction. Audit log one row per case in batch (action=`test_case.bulk_<op>`).
- [ ] **19.5** Frontend mutation: optimistic — update local TanStack Query cache for each id immediately. On error rollback. Show toast `"Updated N cases"` on success.
- [ ] **19.6** Vitest:
  - Select 3 cases, click "Delete" → confirm dialog → mutation fires with `{ ids: [...], action: "delete" }`.
  - Mutation error rolls back optimistic UI (selected cases reappear).
- [ ] **19.7** Test green.
- [ ] **19.8** **Commit** — `feat(api,web): bulk operations on cases with optimistic UI (Closes #M1-15)`.

---

## Task 20: FE — Undo toasts

- [ ] **20.1** Install sonner (`pnpm add sonner`) if not already in M1b. Mount `<Toaster richColors closeButton position="bottom-right" />` at app root (`apps/web/src/routes/__root.tsx`).
- [ ] **20.2** Helper `apps/web/src/lib/undo-toast.ts`:
  ```ts
  export function undoToast<T>({ message, undoFn, dataForRedo }: { message: string; undoFn: () => Promise<T>; dataForRedo?: unknown }) {
    return toast(message, {
      duration: 8000,
      action: {
        label: "Undo",
        onClick: async () => {
          try { await undoFn(); toast.success("Restored"); }
          catch { toast.error("Undo failed"); }
        },
      },
    });
  }
  ```
- [ ] **20.3** Wire to delete mutations:
  - Case delete: after success, call `undoToast({ message: \`\${caseName} deleted\`, undoFn: () => api.post(\`/test-cases/\${id}/restore\`) })`.
  - Suite delete: same pattern (requires backend `POST /suites/:id/restore` — add as Task 2 follow-on if missing).
  - Bulk delete: undo iterates ids → `Promise.all(ids.map(restore))`.
- [ ] **20.4** Vitest `apps/web/src/lib/undo-toast.test.tsx`:
  - Toast renders with Undo button.
  - Clicking Undo within 8s triggers `undoFn` → success toast.
  - Toast auto-dismisses after 8s (advance fake timers).
- [ ] **20.5** Test green.
- [ ] **20.6** **Commit** — `feat(web): undo toasts via sonner for soft-deletes (Closes #M1-13)`.

---

## Task 21: Audit log UI (admin only)

- [ ] **21.1** Backend endpoint `GET /audit-logs` (if not added in M1a — verify, add if missing):
  - Pagination via cursor.
  - Filters: `userId`, `action` (supports `?action=test_case.*` glob), `resourceType`, `from`, `to`.
  - Role gate: ADMIN/OWNER only (403 otherwise).
  - Pytest `apps/api/tests/test_audit_logs.py` — covers filters + role gate + pagination.
- [ ] **21.2** Frontend route `apps/web/src/routes/_app/settings/audit.tsx`:
  - TanStack Router `beforeLoad` checks role; redirects non-admin to `/dashboard` with toast "Admin only".
  - Table with virtualized rows (`@tanstack/react-virtual`) — columns: timestamp (mono), user (avatar+name), action (badge), resource (type+id+link), metadata (collapsible JSON viewer).
  - Filter sidebar: user picker, action multi-select, resource type select, date range picker.
  - Search input → query param `q` (free text contains match on action + resource_id).
- [ ] **21.3** Vitest `apps/web/src/routes/_app/settings/audit.test.tsx`:
  - Non-admin → redirected.
  - Admin → table renders with pagination.
  - Filter change → URL query param updates + refetch.
- [ ] **21.4** Test green.
- [ ] **21.5** **Commit** — `feat(web): audit log UI admin-only`.

---

## Task 22: Workspace settings UI (members + danger zone)

- [ ] **22.1** Route `apps/web/src/routes/_app/settings/workspace.tsx`:
  - Tab 1 "General": name, slug (read-only), region. PATCH `/workspaces/:id`.
  - Tab 2 "Members": list of memberships with avatar, name, email, role dropdown, "Remove" button. "Invite member" modal (email + role select) → POST `/workspaces/:id/members`.
  - Tab 3 "Danger zone": "Delete workspace" red button. Confirmation dialog requires typing workspace slug to enable submit. On confirm: DELETE `/workspaces/:id` → log user out → redirect to login.
- [ ] **22.2** Pytest `apps/api/tests/test_workspace_settings.py` — verify member invite + remove + workspace delete; ensure OWNER role required for danger zone.
- [ ] **22.3** Vitest:
  - Invite modal validates email + selects role.
  - Member remove triggers confirm + DELETE.
  - Danger zone typing wrong slug keeps Delete button disabled; correct slug enables; click → DELETE + redirect.
- [ ] **22.4** Test green.
- [ ] **22.5** **Commit** — `feat(web): workspace settings with members + danger zone`.

---

## Task 23: Auto-defect E2E

- [ ] **23.1** Setup mock external servers via fixtures (use `httpx_mock`/`respx` if test stays in-process; alternatively spin up `pytest-httpserver` for true HTTP-level mocking):
  - Mock Jira endpoint at `http://localhost:8801/rest/api/3/issue` returning `{key: "MOCK-1", id: "1"}`.
  - Mock Slack incoming webhook at `http://localhost:8802/services/T/B/X`.
  - Mock OAuth token endpoint at `http://localhost:8801/oauth/token`.
- [ ] **23.2** Test fixture in `apps/api/tests/e2e/test_auto_defect_e2e.py`:
  - **Pre-state:** Workspace with `strict_zero_validation=true`, Jira integration row + Slack integration row registered, `postgres-mcp` provider registered.
  - **Test case:** 1 step that runs SQL `SELECT count(*) FROM orders WHERE status='paid'` against test postgres (testcontainers), expected count 5 but seeded with 3 rows — so the step's `expect(rows[0].count).to.equal(5)` assertion fails.
  - **Flow:**
    1. POST `/test-cases/:id/run` → 202 + runId.
    2. Poll `GET /runs/:id` until `status != QUEUED && status != RUNNING` (timeout 30s).
    3. Assert `status = FAIL`, `failed_steps = 1`.
    4. Assert defect was auto-filed: `GET /defects?runId=<runId>` returns 1 defect with `agent_diagnosis_kind=REGRESSION` (assertion regex matched), severity matches case priority.
    5. Assert defect.external_issues contains 1 row with `provider="jira"`, `external_id="MOCK-1"`.
    6. Assert mock Jira server received exactly 1 POST `/rest/api/3/issue` call with expected payload (title, severity-mapped priority, labels).
    7. Assert mock Slack webhook received 1 POST with body containing the defect title.
- [ ] **23.3** Run the E2E test in CI — gate the M1d "done" criterion on this test going green.
- [ ] **23.4** Tag the merge candidate `v0.5.0-m1d` on the release branch once all M1-12 through M1-15 and M1-21 through M1-27 acceptance criteria checked off in the GitHub Projects board.
- [ ] **23.5** **Commit** — `test(e2e): auto-defect end-to-end Jira+Slack pipeline (Closes #M1-21 #M1-22 #M1-27)`.

---

## Style requirements (recap)

- TDD ordering: failing test first, then implement, then refactor.
- All new endpoints declare `Depends(require_role(...))` and (when AI-touching) `Depends(require_tier(...))`. M1d is ZERO-only, so no `require_tier` other than confirming ZERO is acceptable.
- Optimistic updates with rollback on every FE mutation that mutates list views.
- Frontend forms use RHF + Zod resolver, never bare `useState` + manual validation.
- Backend: Pydantic v2 schemas in `packages/shared`, services in `apps/api/src/suitest_api/services`, routers thin, DB access via repositories.
- Audit log every mutation, no exceptions.
- Soft-delete + `restore` endpoints for every entity that supports undo.

---

## Self-review checklist

Before declaring M1d done, verify:

1. **Acceptance coverage:**
   - M1-12 (create/edit cases with steps) — Tasks 1, 14
   - M1-13 (suite/case CRUD + soft delete + undo toast) — Tasks 1e, 2, 20
   - M1-14 (drag-reorder via dnd-kit) — Task 14
   - M1-15 (bulk operations) — Task 19
   - M1-21 (rule-based defect creation) — Task 5b
   - M1-22 (Jira/Linear/GitHub via OAuth/PAT/App) — Tasks 7, 8, 9, 13
   - M1-23 (defect status flow) — Tasks 5a, 17
   - M1-24 (requirement CRUD + link) — Task 4
   - M1-25 (traceability matrix functional — verify M1b view still works after writes added)
   - M1-26 (analytics — pre-existing in M1a/M1b; verify still green)
   - M1-27 (CI/CD webhook + Slack) — Tasks 10, 11, 12, 18
2. **Adapter pattern enforced** — every external tracker call goes through `IssueTrackerAdapter` Protocol; no direct `httpx.post(jira_url)` outside the adapter file.
3. **Rule-based categorizer covers each DiagnosisKind enum value** — REGRESSION, FLAKE, INFRA, SPEC_DRIFT, MANUAL_TRIAGE (fallback) all tested with at least one example. Task 5b.3.
4. **Monaco lazy-load verified** — `apps/web/src/components/cases/MonacoCodeEditor.tsx` uses `lazy()` and `<Suspense>`. Bundle analyzer shows Monaco chunk not in initial vendor bundle (run `pnpm build --analyze` and confirm).
5. **Webhook HMAC verified** — Task 11.4 covers bad-signature 401. Task 12.4 covers GitLab token mismatch.
6. **Tier gating sanity** — every endpoint added in this milestone works at tier=ZERO (no `require_tier` rejections). Manual smoke: set `SUITEST_LLM_PROVIDER=none`, restart, run full integration test suite.
7. **Audit log entries present** — pick 3 random mutations, query `/audit-logs?resourceId=...`, confirm row exists with expected `action` name.
8. **Optimistic UI rollback** — disable network in DevTools, attempt a mutation, confirm UI reverts and error toast shows.
9. **Undo toast** — soft-delete a case, click Undo within 8s, confirm restore. Repeat with 9s wait (toast gone) — verify case is still in deleted state recoverable via `POST /test-cases/:id/restore`.
10. **E2E auto-defect** — Task 23 green in CI.
11. **No `Any` / `as any`** — `mypy --strict` passes on `apps/api`, `apps/runner`, `packages/shared`; `tsc --noEmit` clean on `apps/web`.
12. **No barrel files added** — search the diff: no new `index.ts` or `__init__.py` that re-exports.
13. **No secrets in plaintext** — grep diff for `api_key`, `secret`, `password` — all encryption paths route via `packages.core.crypto`.
14. **Visual regression** — `Suitest.html` mockup screens still match within 95% threshold for Cases edit view, Defects, Integrations (run Percy or playwright-visual in CI).
15. **Capability gating** — open Settings → LLM (still placeholder in M1d), confirm tier badge shows ZERO; AI panel hidden; Generate (AI) menu item disabled with tooltip.

---

## Dependency graph (task ordering)

Suggested execution order with parallel opportunities:

```
1 (case CRUD) ───────────────────────┐
                                     │
2 (suite CRUD) ──────────────────────┤
                                     ├──> 14 (FE case editor) ──┐
3 (project CRUD) ────────────────────┤                          │
                                     │                          ├──> 19 (bulk ops)
4 (requirement CRUD) ────────────────┤                          │
                                     │                          ├──> 20 (undo toasts)
6 (adapter Protocol) ──┬──> 7 (Jira) ─┬──> 13 (integration CRUD) ──> 18 (FE integrations) ─┐
                       ├──> 8 (Linear)│                                                    │
                       ├──> 9 (GitHub)│                                                    │
                       └──> 10 (Slack)┘                                                    │
                                                                                           │
5a (manual defect) ──┐                                                                     │
                     ├──> 5b (auto-filer) ────┬──────────────────────────────────────────> 23 (E2E)
                     │                        │
                     └──> 17 (FE defect UI) ──┘
                                                            ┌──> 15 (split generate)
11 (GitHub webhook) ─┬──────────────────────────────────────┤
                     │                                      ├──> 16 (run trigger UI)
12 (GitLab webhook) ─┘                                      │
                                                            └──> 21 (audit UI) ──> 22 (workspace settings)
```

Tasks 1-4, 6 can be parallelized across multiple subagents (no shared state). 7/8/9/10 also parallel after 6 lands. 14 needs 1+2 done. 23 is the final gate.

---

## Hard constraints reminder

- **ZERO tier only for M1d.** No LLM calls. No `require_tier(Tier.LOCAL | Tier.CLOUD)`. Defect categorization is regex-based, not LLM.
- **No `Any` in Python; no `as any` in TS.**
- **No barrel files.**
- **No plaintext secrets.** All integration secrets via AES-GCM.
- **Audit log every mutation.**
- **Workspace scoping on every query.** Repositories take `workspace_id` in every method signature.
- **Optimistic UI** with rollback for delete/update mutations.
- **Soft delete + undo** for cases, suites, projects, requirements. Hard delete only via background retention job (out of M1d scope).
- **Per-tier validation** of test steps strictly enforced — `STEPS_REQUIRE_CODE_IN_ZERO_LLM` error must be raised before any DB write.
- **HMAC verification** on all inbound webhooks; constant-time compare; reject unsigned requests with 401.
- **Adapter Protocol** — every external API call goes through an adapter implementing `IssueTrackerAdapter`.
- **Conventional commits** referencing milestone acceptance: `feat(api): ... (Closes #M1-12)`.
- **Test green before commit.** CI gates on ruff + mypy + pytest + tsc + vitest.

---

## Open questions to surface in PR description (not block work)

- **Webhook dedup window** — chose 60 seconds for same `(project, commit, trigger)`. Confirm acceptable for high-velocity CI projects in PR review.
- **Slack adapter** — using incoming webhooks (no OAuth). When/if we add Slack App for richer features (interactive buttons, @ mentions), webhook adapter remains for backward compat. Punt to M5+.
- **GitLab webhook** — scaffolded but spec says "optional for M1d". Tests are basic; full coverage parity with GitHub deferred to M2 or community contribution.
- **Bulk endpoint hard limit** — chose 100 ids per call. Revisit if/when a workspace has >10k cases and bulk-tagging becomes a UX need.
- **Integration delete behavior** — confirmed: existing external issues stay (FK preserved), new auto-files skip the deleted integration. Document in UI Disconnect dialog copy.
- **OAuth callback failure handling** — if user denies authorization or state token mismatches, redirect to `/settings/integrations?error=oauth_cancelled` with toast. Implementation detail not blocking.

---

## Security review checklist

Run this checklist before tagging `v0.5.0-m1d`:

- [ ] **HMAC verification** — every inbound webhook (`/webhooks/github`, `/webhooks/gitlab`, `/webhooks/jira`) computes HMAC with constant-time compare (`hmac.compare_digest`). No timing oracle.
- [ ] **OAuth state parameter** — `/integrations/jira/connect` generates a CSRF token bound to the session, stored in signed cookie; callback verifies before exchanging code. Same for GitHub App install callback.
- [ ] **Secret encryption** — all `Integration.secrets_encrypted`, `LLMConfig.api_key_encrypted` go through `packages.core.crypto.aes_gcm_encrypt`. Encryption key sourced from `SUITEST_ENCRYPTION_KEY` env, validated 32-byte base64 at app startup.
- [ ] **Secret redaction** — `IntegrationRead` schema explicitly excludes `secrets_encrypted` and never re-derives plaintext. Inspect API responses in tests with a "no plaintext key leaks" assertion (regex check for `sk-`, `ghp_`, `xoxb-`, `lin_` prefixes in JSON).
- [ ] **SQL injection** — all queries via SQLAlchemy ORM or `text()` with bound params. Grep the diff for raw `execute(f"...{var}...")` — none allowed.
- [ ] **XSS** — UI defect descriptions render via React text nodes only; never use `dangerouslySetInnerHTML`. Markdown rendering uses `react-markdown` with safe defaults (no raw HTML).
- [ ] **Webhook secret per integration** — different secrets per workspace's GitHub integration row prevents one tenant's webhook from triggering another's runs.
- [ ] **Rate limiting** — `/webhooks/*` endpoints have a separate (higher) bucket via `slowapi` middleware. Auto-defect external filing arq job has a workspace-level concurrency cap of 4 to avoid hammering Jira/Linear on a 100-failure run.
- [ ] **Role gating** — verified: project CRUD = ADMIN/OWNER, integration CRUD = ADMIN/OWNER, audit log = ADMIN/OWNER, workspace danger zone = OWNER only. Case/suite/requirement CRUD = QA+.
- [ ] **Workspace isolation** — repository methods take `workspace_id` as a required parameter; cross-tenant access returns 404 (not 403) to avoid enumeration. Validated in Task 1a.9 pattern across all entities.
- [ ] **Audit log immutability** — `audit_logs` table has no UPDATE or DELETE endpoints. Verify via API surface scan.
- [ ] **CORS** — `/webhooks/*` accepts POST from anywhere (it's the whole point); other endpoints CORS-locked to web app origin.

---

## Performance & observability checklist

- [ ] **N+1 query elimination:** list endpoints (`GET /test-cases`, `GET /defects`) use `selectinload(TestCase.steps)` and `selectinload(TestCase.tags)` — no per-row queries. Verify via `pytest --queries-count=1` assertion in list-endpoint tests.
- [ ] **Indexes verified:** `EXPLAIN ANALYZE` for hot queries:
  - `SELECT * FROM test_cases WHERE suite_id = ? AND deleted_at IS NULL ORDER BY name LIMIT 20` → uses `ix_test_cases_suite_status`.
  - `SELECT * FROM defects WHERE workspace_id = ? AND status = 'OPEN' ORDER BY created_at DESC LIMIT 20` → uses `ix_defects_workspace_status`.
  - `SELECT * FROM run_steps WHERE run_id = ? ORDER BY step_order` → uses `ix_run_steps_run_outcome`.
- [ ] **Bulk endpoint atomicity:** `POST /test-cases/bulk-update` runs in a single transaction. For 100 ids, P99 latency target <500ms (benchmark in `apps/api/tests/perf/test_bulk_perf.py` — flag if regressed).
- [ ] **Auto-defect filer latency:** rule-based categorization is O(rules × len(error_message)). For a 100kB stack trace, runtime should be <10ms — verify with `pytest --benchmark` in Task 5b.3.
- [ ] **External adapter timeouts:** every `httpx.AsyncClient.post` has `timeout=10.0`. arq job timeouts at 30s.
- [ ] **Connection pool sizing:** `httpx.AsyncClient(limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))` shared across adapter instances via DI.
- [ ] **Metrics (Prometheus):**
  - `suitest_defects_auto_filed_total{workspace_id, diagnosis_kind}` counter.
  - `suitest_external_issue_created_total{provider, ok}` counter.
  - `suitest_webhook_received_total{provider, event}` counter.
  - `suitest_test_case_mutations_total{action}` counter.
  - Export via existing `/metrics` endpoint (M0).
- [ ] **Tracing (OpenTelemetry):** spans around `DefectAutoFiler.file_for_failed_step`, each adapter call, each webhook handler. Span attributes include `workspace_id`, `defect_id`, `provider`. M4 wires the full OTLP exporter; M1d just ensures spans are created via existing helpers in `packages.core.tracing`.
- [ ] **Slow query log:** Postgres `log_min_duration_statement = 200ms` in dev compose.

---

## Migration list summary (Alembic)

Migrations introduced in M1d, in order:

1. `1Xxx_add_public_id_sequences.py` — create `test_case_public_seq`, `defect_public_seq`, `requirement_public_seq`, `run_public_seq` if not present (idempotent). Backfill `public_id` for existing rows.
2. `1Xxx_add_workspace_settings.py` — add `workspaces.strict_zero_validation BOOLEAN NOT NULL DEFAULT TRUE`. Existing workspaces get default `true`.
3. `1Xxx_add_suite_order.py` — add `test_cases.order_in_suite INTEGER NOT NULL DEFAULT 0`. Backfill: per suite, `ROW_NUMBER() OVER (PARTITION BY suite_id ORDER BY created_at)`.
4. `1Xxx_runs_dedup.py` — add partial unique index for webhook dedup.
5. `1Xxx_defects_auto_dedup.py` — add partial unique index for auto-filer dedup.
6. `1Xxx_projects_gating_suite.py` — add `projects.gating_suite_id` nullable FK to `suites.id`.

All migrations must:
- Have `def downgrade()` defined and tested.
- Run idempotently when reapplied via `alembic upgrade head --sql` dry-run.
- Pass `pytest apps/api/tests/migrations/test_round_trip.py` (upgrade-then-downgrade).

---

## Hand-off note to next milestone

After M1d ships and `v0.5.0-m1d` is tagged, M2 picks up:

- Deterministic generators (OpenAPI, Recorder, Crawler) — the disabled split-button items get wired.
- MCP plugin universal CRUD UI — disabled bundle browser becomes interactive.
- Mixed-MCP test case execution proof.
- Code export endpoint (Playwright/Cypress/Selenium).

ZERO-tier as TestRail+Playwright replacement is **complete at end of M1d**. M2 expands what ZERO can generate from external sources; M3 introduces LLM tier.
