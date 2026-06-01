# docs/API.md

> REST endpoints + WebSocket events Suitest OSS. Semua route di-mount di `/api/v1/*` kecuali disebutkan lain. Input/output di-validate dengan **Pydantic v2** (lihat `packages/shared/schemas/`).

> ℹ️ **Built today (M0–M3 foundation):** auth, workspaces, TCM CRUD, runs, defects, requirements, integrations, webhooks, analytics, `/capabilities`, `/auth/me`, `WS /ws`, deterministic generators (M2-1..M2-5), MCP-provider CRUD + `/discover`·`/invoke`·`/routing` (M2-6..M2-9), **`/workspaces/:id/llm-config` (GET/PUT/test/DELETE/models — M3-2/M3-3)**. **Not built (M3–M4 spec):** agent `/agent/*` sessions+replay, eval, sdk, code export. Build truth = `apps/api/src/suitest_api/routers/` + [ROADMAP.md](./ROADMAP.md).
>
> Cross-links: [DATA_MODEL.md](./DATA_MODEL.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md) · [MCP_PLUGINS.md](./MCP_PLUGINS.md) · [AUTONOMY.md](./AUTONOMY.md) · [GENERATORS.md](./GENERATORS.md) · [pivot design memo](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md).

---

## 1. Authentication

Suitest OSS pakai **FastAPI-Users** (self-host friendly, multi-tenant) untuk session + OAuth, plus opaque API token untuk integrasi.

| Method | Header | Used by |
|--------|--------|---------|
| Session cookie | `Cookie: suitest_session=...` | Web app (FastAPI-Users cookie backend) |
| OAuth (Google / GitHub) | redirect flow `/auth/oauth/{provider}/{login,callback}` | Web app SSO |
| Bearer token | `Authorization: Bearer suit_xxxxx` | CI integrations, SDKs |

**API token format.** Default = **opaque** random 32-byte token, prefix `suit_`, stored as `sha256(token)` server-side. Verification = constant-time hash compare. Tokens **never** retrievable after creation (display once).

Optional alt format (set `SUITEST_API_TOKEN_FORMAT=paseto`): signed **PASETO v4 local** tokens with workspace + scopes claims. Useful for stateless ephemeral CI tokens. Disabled by default to keep ZERO setup trivial.

Workspace context via `X-Workspace-Id: ws_xxx` header atau path segment `/api/v1/ws/:wsId/...`.

**401** unauthenticated, **403** authenticated tapi tidak punya akses workspace/resource.

---

## 2. Conventions

- **Versioning:** path-based (`/api/v1`). Breaking changes → `/api/v2`.
- **Pagination:** cursor-based via `?cursor=<id>&limit=20`. Default limit 20, max 100.
- **Filtering:** query string, repeatable params (`?status=open&status=in_progress`).
- **Sorting:** `?sort=createdAt:desc`.
- **Errors:**
  ```json
  {
    "error": {
      "code": "RESOURCE_NOT_FOUND",
      "message": "Test case TC-9999 not found",
      "details": { "resourceType": "test_case", "id": "TC-9999" }
    }
  }
  ```
- **Timestamps:** ISO 8601 UTC (`2026-05-22T14:32:01.024Z`).
- **IDs di response:** public ID (`TC-1045`) di field `publicId`, opaque `id` (cuid) tetap ada untuk internal lookups.
- **Optimistic concurrency:** mutation endpoints on test cases accept an optional `If-Unmodified-Since` request header (HTTP-date). Currently honoured by `PATCH /test-cases/:id` and `PATCH /test-cases/:id/steps`. If the header is older than the row's `updated_at`, the server returns **409 `CONCURRENT_MODIFICATION`** with `details.serverUpdatedAt` so the client can refetch and retry. Header absent → last-write-wins (existing behaviour).

### 2.1 Capability/tier-aware error codes

Endpoints yang menyentuh AI/MCP/autonomy memunculkan error code khusus supaya FE bisa render banner/gate yang jelas.

| Code | HTTP | Trigger | Body shape |
|------|:----:|---------|------------|
| `LLM_DISABLED` | **503** | Workspace tier=`ZERO` (no LLM configured) tapi endpoint butuh LLM | `{"error":{"code":"LLM_DISABLED","message":"This feature requires an LLM provider. Configure one in Settings → LLM.","docsUrl":"/docs/capability-tiers"}}` |
| `STEPS_REQUIRE_CODE_IN_ZERO_LLM` | **400** | Saat membuat/menjalankan case di ZERO, ada step yang hanya punya `action` tanpa `code` | `{"error":{"code":"STEPS_REQUIRE_CODE_IN_ZERO_LLM","message":"Step #3 has no executable code. ZERO tier cannot translate action → MCP call at runtime.","details":{"stepIndex":3,"caseId":"ckxxx"}}}` |
| `AUTONOMY_LEVEL_INSUFFICIENT` | **403** | Action butuh autonomy lebih tinggi (mis. auto-close defect saat level=`assist`) | `{"error":{"code":"AUTONOMY_LEVEL_INSUFFICIENT","message":"Auto-close requires autonomy=semi_auto. Current: assist.","details":{"required":"semi_auto","current":"assist"},"docsUrl":"/docs/autonomy"}}` |
| `MCP_PROVIDER_NOT_REGISTERED` | **404** | Step/run reference MCP provider yang belum terdaftar di workspace | `{"error":{"code":"MCP_PROVIDER_NOT_REGISTERED","message":"MCP provider 'postgres-mcp' not registered.","details":{"name":"postgres-mcp"},"docsUrl":"/docs/mcp-plugins"}}` |
| `MCP_PROVIDER_UNHEALTHY` | **503** | Provider terdaftar tapi `health_status != healthy` saat dipanggil | `{"error":{"code":"MCP_PROVIDER_UNHEALTHY","message":"MCP provider 'browser-use-mcp' is unhealthy (last check: 2026-05-26T10:12:01Z).","details":{"providerId":"mcp_xxx","lastHealth":"..."}}}` |
| `TARGET_KIND_UNSUPPORTED_IN_TIER` | **400** | Generator/run mencoba `target_kind` yang butuh LLM di ZERO (mis. `FE_WEB` semantic crawl) | `{"error":{"code":"TARGET_KIND_UNSUPPORTED_IN_TIER","message":"Semantic FE_WEB crawl requires CLOUD or LOCAL tier.","details":{"targetKind":"FE_WEB","tier":"ZERO","alternatives":["/api/v1/generators/crawler"]}}}` |
| `INVALID_SOURCE_FOR_TIER` | **400** | `/agent/generate/cases` with a `source` whose tier-appropriate counterpart is the deterministic generator (see §3.10) | `{"error":{"code":"INVALID_SOURCE_FOR_TIER","message":"OpenAPI generation is deterministic and available in ZERO tier via /generators/openapi.","details":{"source":"OPENAPI","tier":"ZERO","useEndpoint":"/api/v1/generators/openapi"}}}` |
| `CONCURRENT_MODIFICATION` | **409** | `If-Unmodified-Since` predates server `updated_at` on a mutating endpoint | `{"error":{"code":"CONCURRENT_MODIFICATION","message":"Test case was modified by another client.","details":{"resourceType":"test_case","id":"TC-1045","serverUpdatedAt":"2026-05-26T07:11:00Z"}}}` |
| `CROSS_WORKSPACE_LINK` | **400** | Attempt to link a requirement and case that live in different workspaces | `{"error":{"code":"CROSS_WORKSPACE_LINK","message":"Requirement REQ-401 and case TC-1045 belong to different workspaces.","details":{"requirementWorkspaceId":"ws_a","caseWorkspaceId":"ws_b"}}}` |
| `CROSS_WORKSPACE_IDS` | **400** | Bulk endpoint received one or more ids outside the caller's workspace | `{"error":{"code":"CROSS_WORKSPACE_IDS","message":"3 id(s) belong to a different workspace.","details":{"offendingIds":["TC-2001","TC-2002","TC-2007"]}}}` |
| `BULK_LIMIT_EXCEEDED` | **400** | Bulk endpoint called with more than the documented cap (currently 100 ids) | `{"error":{"code":"BULK_LIMIT_EXCEEDED","message":"bulk-update accepts at most 100 ids per request.","details":{"received":137,"limit":100}}}` |

FE rule of thumb: any 4xx/5xx with a `code` in the table above → render the **Capability banner** (not toast). For `CONCURRENT_MODIFICATION` and `CROSS_WORKSPACE_*`, render inline form error instead.

---

## 3. REST endpoints

### 3.0 Capabilities (public)

Surfaces tier + autonomy + MCP + embeddings state. **No auth required** — frontend boot fetches this before login screen so the login UI can show tier badge.

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/capabilities` | Public; full snapshot |
| GET | `/capabilities/health` | Public; lightweight: `{tier, status, uptime}` for k8s liveness |

> Authoritative schema: see [CAPABILITY_TIERS.md § 10](./CAPABILITY_TIERS.md#10-capability-endpoint-contract). The shape below mirrors that section verbatim; any drift here is a bug in this doc, not in the contract.

**Sample `GET /capabilities` response (CLOUD tier):**
```json
{
  "tier": "CLOUD",
  "llm": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-5",
    "base_url": null,
    "is_test_provider": false
  },
  "embeddings": {
    "enabled": true,
    "backend": "openai",
    "model": "text-embedding-3-small",
    "dim": 1536
  },
  "features": {
    "manual_tcm": true,
    "deterministic_runner": true,
    "deterministic_generator_openapi": true,
    "deterministic_generator_recorder": true,
    "deterministic_generator_crawler": true,
    "ai_generation": true,
    "ai_execution_agentic": true,
    "ai_diagnose": true,
    "ai_conversation": true,
    "semantic_search": true,
    "fts_search": true,
    "auto_defect_filing_ai": true,
    "auto_defect_filing_rule": true
  },
  "autonomy": {
    "available": ["manual", "assist", "semi_auto", "auto"],
    "default": "assist"
  },
  "mcpProviders": [
    { "id": "mcp_aaa", "name": "playwright-mcp", "kind": "playwright", "health": "healthy", "isDefault": true },
    { "id": "mcp_bbb", "name": "api-mcp",        "kind": "api",        "health": "healthy", "isDefault": true },
    { "id": "mcp_ccc", "name": "postgres-mcp",   "kind": "postgres",   "health": "unknown", "isDefault": false }
  ],
  "version": "1.0.0"
}
```

**Sample `GET /capabilities/health` response:**
```json
{ "tier": "ZERO", "status": "ok", "uptimeSec": 123456 }
```

### 3.1 Auth & workspace

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/auth/me` | Current user + memberships |
| GET | `/workspaces` | List workspaces user |
| POST | `/workspaces` | Create workspace |
| GET | `/workspaces/:id` | Workspace detail |
| PATCH | `/workspaces/:id` | Update workspace settings |
| GET | `/workspaces/:id/members` | List members |
| POST | `/workspaces/:id/members` | Invite member (email + role) |
| DELETE | `/workspaces/:id/members/:userId` | Remove member |
| DELETE | `/workspaces/:id` | **OWNER only** — destroy workspace; returns `202 Accepted` + async cleanup job id |
| GET | `/audit-logs` | Workspace-scoped audit trail, cursor-paginated (`?cursor=&action=&resource_type=&user_id=&from=&to=&limit=50`) |

**M1e local auth + invite-only onboarding**

| Method | Path | Tujuan |
|--------|------|--------|
| POST | `/auth/cookie/login` | Password login; FastAPI-Users form body `username` + `password`; sets `suitest_session` cookie |
| POST | `/auth/forgot-password` | Start reset-password flow; stores encrypted reset link for super-admin review until SMTP exists |
| POST | `/auth/reset-password` | Complete FastAPI-Users reset-password flow |
| PATCH | `/api/v1/users/me/password` | Current user changes password; requires `current_password` + `new_password` |
| POST | `/api/v1/workspaces/:id/invitations` | ADMIN/OWNER creates invite link; returns raw link once |
| GET | `/api/v1/workspaces/:id/invitations` | ADMIN/OWNER lists invitations |
| POST | `/api/v1/invitations/:id/revoke` | ADMIN/OWNER revokes invitation |
| POST | `/api/v1/invitations/:id/resend` | ADMIN/OWNER rotates token and returns new raw link once |
| GET | `/api/v1/invitations/validate?token=` | Public invite validation for `/accept-invite` |
| POST | `/api/v1/auth/accept-invite` | Public accept invite; creates/activates user, membership, and session cookie |
| POST | `/api/v1/admin/users/:userId/reset-password` | `is_superuser` only; returns one-time temporary password |
| GET | `/api/v1/admin/password-reset-requests` | `is_superuser` only; lists encrypted reset links after decryption |

`POST /auth/register` is intentionally not mounted after M1e. Suitest OSS is invite-only after first-install bootstrap.

**DELETE `/workspaces/:id`** body (required):
```json
{ "confirm_slug": "acme-prod" }
```
`confirm_slug` must equal the workspace's `slug`. Mismatch → `400` with `details.expectedSlug` redacted. On success:
```json
{ "jobId": "job_xxx", "status": "QUEUED" }
```
Cleanup is asynchronous: tears down MCP provider sessions, deletes artifacts in R2, drops rows in single transaction per resource family. Subscribe to `workspace:<wsId>` for the terminal `workspace.deleted` event (or poll `GET /jobs/:jobId` — out of scope for M1d).

**GET `/audit-logs`** notes:
- `action` accepts glob (`integration.*`, `case.deleted`, `*`). Defaults to all.
- `from` / `to` are ISO 8601 UTC, inclusive.
- `limit` default 50, max 200.
- Cursor is opaque (encodes `(created_at, id)` pair). When the response omits `next_cursor`, the caller has reached the head of the log.
- Returns `403` if caller is not at least `ADMIN` in the workspace.

Response:
```json
{
  "items": [
    {
      "id": "audit_xxx",
      "action": "case.updated",
      "resourceType": "test_case",
      "resourceId": "TC-1045",
      "userId": "u_maya",
      "createdAt": "2026-05-26T07:11:00Z",
      "details": { "diff": { "priority": ["P1", "P0"] } }
    }
  ],
  "next_cursor": "eyJjcmVhdGVkQXQiOiI..."
}
```

### 3.2 Projects

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/projects` | List projects (workspace-scoped) |
| POST | `/projects` | Create project |
| GET | `/projects/:id` | Detail |
| PATCH | `/projects/:id` | Update |
| DELETE | `/projects/:id` | Soft delete |

### 3.3 Test cases

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/test-cases` | List, supports filters: `?suiteId&status&source&priority&tag&q` |
| POST | `/test-cases` | Create manual case |
| GET | `/test-cases/:id` | Detail with steps |
| PATCH | `/test-cases/:id` | Update metadata (honours `If-Unmodified-Since`) |
| DELETE | `/test-cases/:id` | Soft delete |
| POST | `/test-cases/:id/restore` | Revive soft-deleted case; idempotent |
| POST | `/test-cases/:id/duplicate` | Clone |
| POST | `/test-cases/:id/run` | Trigger ad-hoc run |
| PATCH | `/test-cases/:id/steps` | Replace all steps (atomic, honours `If-Unmodified-Since`) |
| PATCH | `/test-cases/:id/steps/reorder` | Atomic reorder of existing step ids |
| POST | `/test-cases/:id/steps` | Append step |
| POST | `/test-cases/bulk-update` | Bulk action across ≤100 cases (single transaction) |
| POST | `/steps/test-once` | Dispatch a single step through MCP runner; returns inline result + artifact urls (role: QA+) |

**POST `/test-cases/:id/restore`** — no body. Returns `204 No Content`. Re-POST after a successful restore returns `204` (idempotent). `404` if the case never existed or was hard-deleted.

**POST `/test-cases/bulk-update`** body:
```json
{
  "ids": ["TC-1045", "TC-1046", "TC-1047"],
  "action": "set_priority",
  "payload": { "priority": "P0" }
}
```
Valid `action` values: `delete` (soft), `move_to_suite` (`payload.suiteId` required), `set_priority` (`payload.priority`), `add_tags` (`payload.tags: string[]`), `remove_tags` (`payload.tags: string[]`).

- Hard cap **100** ids per request → `400 BULK_LIMIT_EXCEEDED` if exceeded.
- All ids must belong to caller's workspace → `400 CROSS_WORKSPACE_IDS` with offending ids if not.
- Runs in a single DB transaction; either all rows mutate or none.
- Emits one `audit_log` row per mutated case; ids returned in response so the UI can correlate.

Response:
```json
{ "updated": 3, "audit_ids": ["audit_a", "audit_b", "audit_c"] }
```

**PATCH `/test-cases/:id/steps/reorder`** body:
```json
{ "step_ids_in_order": ["step_a", "step_c", "step_b"] }
```
Atomic: every existing step id must appear exactly once; otherwise `400` with `details.missing` / `details.duplicate` / `details.unknown`. Returns the updated step list (same shape as `GET /test-cases/:id`'s `steps`).

**POST `/steps/test-once`** body:
```json
{
  "step": {
    "action": "Open /login",
    "expected": "Login form visible",
    "mcpProvider": "playwright-mcp",
    "targetKind": "FE_WEB",
    "code": "await page.goto('/login'); await expect(page.locator('form')).toBeVisible();"
  },
  "context": {
    "env": "staging",
    "variables": { "BASE_URL": "https://staging.example.com" }
  }
}
```
Synchronous: dispatches one step through the MCP runner using the workspace's default routing (override by setting `step.mcpProvider`). Returns:
```json
{
  "outcome": "PASS",
  "durationMs": 812,
  "logs": [
    { "level": "info", "message": "navigation complete", "time": "..." }
  ],
  "artifacts": [
    { "kind": "screenshot", "url": "https://r2.suitest.io/signed/..." }
  ]
}
```
Role gate: `QA` or higher. Errors propagate as standard MCP errors (`MCP_PROVIDER_NOT_REGISTERED`, `MCP_PROVIDER_UNHEALTHY`, `STEPS_REQUIRE_CODE_IN_ZERO_LLM`). Used by the [UI_SPEC §3.2.2 "Test step now"](./UI_SPEC.md) inline button.

**Sample POST `/test-cases`**:
```json
{
  "suiteId": "ckxxxx",
  "name": "Login with valid credentials",
  "description": "...",
  "priority": "P0",
  "source": "MANUAL",
  "steps": [
    {
      "order": 1,
      "action": "Open /login",
      "expected": "Login form visible",
      "mcpProvider": "playwright-mcp",
      "targetKind": "FE_WEB",
      "code": "await page.goto('/login'); await expect(page.locator('form')).toBeVisible();"
    },
    {
      "order": 2,
      "action": "Type valid creds",
      "expected": "Dashboard loads",
      "mcpProvider": "playwright-mcp",
      "targetKind": "FE_WEB"
    }
  ],
  "tags": ["smoke", "auth"]
}
```

**Step validator behaviour (per tier).** Validator runs on `POST /test-cases` and `PATCH /test-cases/:id/steps`:

| Tier | Step has `code` | Step has only `action` | Step missing both |
|------|-----------------|-----------------------|-------------------|
| **ZERO** | accepted | **400 `STEPS_REQUIRE_CODE_IN_ZERO_LLM`** (workspace must have `strict_zero_validation=true`, default on) | 400 invalid |
| **LOCAL/CLOUD** | accepted | accepted (action→code translated at run time) | 400 invalid |

In all tiers `mcpProvider` is required; missing field → 400 `MCP_PROVIDER_NOT_REGISTERED` if name unknown to workspace, else accepted. `targetKind` defaults to `FE_WEB` when omitted.

### 3.4 Suites

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/suites?projectId=...` | List |
| POST | `/suites` | Create |
| PATCH | `/suites/:id` | Rename / reorder (optional `case_order: string[]` for atomic case reorder) |
| DELETE | `/suites/:id` | Soft delete (cascade requires confirm) |
| POST | `/suites/:id/restore` | Revive soft-deleted suite; idempotent (returns 204) |

**PATCH `/suites/:id`** body fields (all optional, at least one required):
```json
{
  "name": "Smoke — Checkout",
  "description": "...",
  "case_order": ["TC-1045", "TC-1046", "TC-1047"]
}
```
When `case_order` is supplied, every case id currently in the suite must appear exactly once; otherwise `400` with `details.missing` / `details.unknown`. Case ids outside this suite → `400 CROSS_WORKSPACE_IDS` if cross-workspace, else `400` with `details.notInSuite`. The reorder runs in the same transaction as any metadata update.

**POST `/suites/:id/restore`** — no body. Returns `204 No Content`. Idempotent: re-POST after restore returns `204`. Does **not** auto-restore child cases — those must be restored individually via `POST /test-cases/:id/restore` (or future `POST /suites/:id/restore?cascade=true`, out of scope for M1d).

### 3.5 Runs

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/runs` | List, filters: `?status&projectId&branch&env` |
| POST | `/runs` | Create + queue run |
| GET | `/runs/:id` | Detail with summary |
| GET | `/runs/:id/steps` | Run steps with outcomes |
| GET | `/runs/:id/logs?cursor=...` | Streaming-friendly cursor pagination |
| GET | `/runs/:id/artifacts` | List artifacts |
| GET | `/runs/:id/artifacts/:artifactId` | Signed URL ke R2 |
| POST | `/runs/:id/cancel` | Cancel |
| POST | `/runs/:id/rerun` | Re-trigger same run config |

**Sample POST `/runs`**:
```json
{
  "projectId": "ckxxxx",
  "name": "Checkout E2E · Chrome 124",
  "selection": { "type": "suite", "ids": ["ckxxxx"] },
  // or { "type": "cases", "ids": ["TC-1045", "TC-1046"] }
  // or { "type": "tag", "tags": ["smoke"] }
  "branch": "main",
  "commitSha": "a7f3e21",
  "env": "staging",
  "trigger": "MANUAL",
  "parallelism": 4,
  "mcpRoutingOverride": {
    "FE_WEB": "playwright-mcp-headful",
    "BE_REST": "api-mcp"
  }
}
```

> `mcpProvider` is **no longer top-level** on a run — each `TestStep` carries its own. The optional `mcpRoutingOverride` maps `targetKind → provider name` and lets a single run flip provider per classification (e.g. swap headless for headful). The runner persists `tier_at_runtime` on the `Run` row so historical reproductions stay correct.

### 3.6 Defects

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/defects` | List, filters: `?status&severity&assigneeId&component` |
| POST | `/defects` | Create manual (agent juga pakai endpoint sama internal) |
| GET | `/defects/:id` | Detail |
| PATCH | `/defects/:id` | Update (status, assignee, severity) |
| POST | `/defects/:id/sync-external` | Force re-sync ke Jira/Linear |
| GET | `/defects/:id/timeline` | Activity log |

### 3.7 Requirements & traceability

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/requirements` | List with link counts |
| POST | `/requirements` | Create |
| GET | `/requirements/:id` | Detail with linked cases + defects |
| POST | `/requirements/:id/links` | Add link `{ caseId }` |
| DELETE | `/requirements/:id/links/:caseId` | Remove link |
| GET | `/traceability/matrix?projectId=...` | Full matrix for grid view |

**Sample matrix response**:
```json
{
  "requirements": [
    { "id": "REQ-401", "title": "Sign in with Google", "tests": ["TC-1045"], "defects": ["SUIT-1284"] }
  ],
  "cases": [ { "id": "TC-1045", "name": "...", "source": "AI", "status": "FAIL" } ],
  "defects": [ { "id": "SUIT-1284", "title": "...", "severity": "CRITICAL", "status": "OPEN" } ]
}
```

### 3.8 Analytics

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/analytics/kpis?projectId&period=7d` | Pass rate, duration, runs count |
| GET | `/analytics/pass-rate?projectId&period=30d` | Time series |
| GET | `/analytics/flaky?projectId&minRate=0.05` | Flaky test list |
| GET | `/analytics/heatmap?projectId&period=14d` | Run count grid (day × hour) |
| GET | `/analytics/readiness?projectId` | Release readiness score + blockers |
| GET | `/analytics/coverage?projectId` | Coverage by suite + requirement |

### 3.9 Integrations

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/integrations` | List for workspace |
| POST | `/integrations` | Connect new integration |
| GET | `/integrations/:id` | Detail (secrets redacted) |
| PATCH | `/integrations/:id` | Update config |
| POST | `/integrations/:id/test` | Smoke-test connection (existing, persisted integration) |
| DELETE | `/integrations/:id` | Disconnect |
| POST | `/integrations/:id/sync` | Trigger manual sync |
| POST | `/integrations/jira/test-connection` | Validate Jira credentials **before** persisting |
| POST | `/integrations/github/test-connection` | Validate GitHub App credentials **before** persisting |

**Pre-save credential validation.** The `*/test-connection` endpoints spawn the relevant MCP adapter once with the provided env, hit a cheap "whoami"-style tool, and discard the process. They never persist a row in `integrations`. Used by the Settings → Integrations connect modal to flip the form's status pill before the user clicks Save. M1d Jira ships **PAT / cloud-token only** (no OAuth flow); OAuth is deferred to v1.x.

**POST `/integrations/jira/test-connection`** body:
```json
{
  "jira_url": "https://acme.atlassian.net",
  "jira_email": "ops@acme.com",
  "jira_token": "ATATT3xFfGF0...",
  "jira_auth_type": "cloud_token"
}
```
`jira_auth_type` ∈ `cloud_token | pat`. Spawns `jirac-mcp` with env `JIRA_URL` / `JIRA_EMAIL` / `JIRA_TOKEN` / `JIRA_AUTH_TYPE`, then invokes `jira_api_request` tool against `GET /rest/api/3/myself`. Response:
```json
{ "ok": true, "account_id": "5b10ac8d82e05b22cc7d4ef5", "display_name": "Maya Ops" }
```
or
```json
{ "ok": false, "error": { "code": "JIRA_AUTH", "message": "401 Unauthorized" } }
```

**POST `/integrations/github/test-connection`** body:
```json
{
  "app_installation_id": "48291023",
  "private_key_pem": "<PEM-encoded RSA private key — see docs/DEPLOYMENT.md for GitHub App setup>"
}
```
Spawns `github-mcp-server` with the installation token derived from the App private key, calls `get_authenticated_user` (or `list_repositories` if user endpoint unavailable for App tokens). Response shape mirrors Jira: `{ ok, account_id?, display_name?, error? }`. The `private_key_pem` field is never persisted by this endpoint and never logged.

Both endpoints enforce a 10s timeout end-to-end and require role `ADMIN`+.

**MCP integration POST body**:
```json
{
  "kind": "MCP_BROWSER_USE",
  "name": "Browser-Use Staging",
  "config": {
    "endpoint": "browser-use://staging",
    "concurrency": 4,
    "headless": true
  },
  "secrets": {
    "apiKey": "buk_xxxxx"
  }
}
```

> The `kind` enum is expanded for the OSS pivot. Valid values: `GITHUB, GITLAB, JENKINS, JIRA, LINEAR, SLACK, OPENAPI, MCP_BROWSER_USE, MCP_PLAYWRIGHT, MCP_CUSTOM, MCP_API, MCP_POSTGRES, MCP_KUBERNETES, MCP_GRAPHQL, MCP_GRPC, MCP_APPIUM, MCP_MONGO, MCP_MYSQL`. Full list lives in [DATA_MODEL.md §6](./DATA_MODEL.md#6-enums). For `MCP_*` kinds, prefer the dedicated MCP registry under [§3.16 MCP Providers](#316-mcp-providers) — the `/integrations` endpoint is kept for backwards compatibility and CI/CD providers.

### 3.10 Agent (AI)

| Method | Path | Tujuan |
|--------|------|--------|
| POST | `/agent/sessions` | Start a new agent session |
| GET | `/agent/sessions/:id` | Session + messages |
| POST | `/agent/sessions/:id/messages` | Send user message (returns SSE stream) |
| POST | `/agent/generate/cases` | One-shot generation, lihat detail di bawah |
| POST | `/agent/diagnose/defect/:defectId` | Re-run root-cause analysis |
| POST | `/agent/suggest/edge-cases` | Saran edge case untuk existing case |

**POST `/agent/generate/cases`** request:
```json
{
  "source": "PRD",   // PRD | OPENAPI | URL_SEMANTIC | MCP
  "input": {
    "type": "text",
    "value": "PRD-2026-Q1 § 4.2 ..."
    // OR { "type": "url", "value": "https://api.suitest.io/openapi.json" }
    // OR { "type": "documentId", "value": "doc_xxx" }
  },
  "targetSuiteId": "ckxxxx",
  "targetKind": "FE_WEB",   // optional, classifier override
  "options": {
    "maxCases": 10,
    "priorityHint": "P0",
    "tagPrefix": "oauth"
  }
}
```

Response: **Server-Sent Events** stream
```
event: progress
data: { "stage": "reading", "message": "Reading PRD section..." }

event: case
data: { "id": "draft_1", "publicId": "TC-1050", "name": "Google OAuth — happy path", "steps": [...] }

event: case
data: { "id": "draft_2", ... }

event: complete
data: { "totalGenerated": 5, "sessionId": "sess_xxx", "tokensUsed": 4821 }
```

Frontend pakai EventSource untuk render cases streaming masuk.

**Tier behaviour for `/agent/generate/cases`.** All four `source` values require an LLM. In ZERO tier this endpoint **always** errors — but the error shape depends on whether a deterministic alternative exists:

| `source` | ZERO behaviour | LOCAL / CLOUD behaviour |
|----------|----------------|--------------------------|
| `PRD` | **503 `LLM_DISABLED`** (no deterministic equivalent) | Streams cases |
| `URL_SEMANTIC` | **503 `LLM_DISABLED`** (heuristic crawler ≠ semantic understanding) | Streams cases |
| `MCP` | **503 `LLM_DISABLED`** (LLM-driven tool discovery) | Streams cases |
| `OPENAPI` | **400 `INVALID_SOURCE_FOR_TIER`** with hint `{"useEndpoint":"/api/v1/generators/openapi"}` — the deterministic `/generators/openapi` produces identical cases without an LLM, so callers should switch | Streams cases |

> The decision to return **400 + hint** for `OPENAPI` in ZERO (instead of auto-routing) is intentional: keep semantics of `/agent/*` as "AI agent endpoints", and surface the deterministic counterpart explicitly so users learn the right tool. See [§3.17 Generators](#317-generators).

Sample 400 body:
```json
{
  "error": {
    "code": "INVALID_SOURCE_FOR_TIER",
    "message": "OpenAPI generation is deterministic and available in ZERO tier via /generators/openapi.",
    "details": { "source": "OPENAPI", "tier": "ZERO", "useEndpoint": "/api/v1/generators/openapi" }
  }
}
```

### 3.11 Documents (RAG sources)

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/documents` | List indexed sources |
| POST | `/documents` | Add (PRD URL, OpenAPI URL, frontend URL) |
| POST | `/documents/:id/resync` | Re-index |
| DELETE | `/documents/:id` | Remove + drop chunks |

### 3.12 Webhooks (inbound from CI/git providers)

| Method | Path | Provider |
|--------|------|----------|
| POST | `/webhooks/github` | GitHub Actions, push, PR |
| POST | `/webhooks/gitlab` | GitLab CI |
| POST | `/webhooks/jenkins` | Jenkins post-build |
| POST | `/webhooks/jira` | Jira issue updates (for status sync back) |

Setiap webhook verifies HMAC signature dengan secret yang di-set saat connect integration.

### 3.13 SDK / Public API (untuk integrasi user)

Same `/api/v1/*` endpoints tapi via Bearer token. Rate-limited 1000 req/min per token.

Tambahan helper:
| Method | Path | Tujuan |
|--------|------|--------|
| POST | `/sdk/runs/start` | Concise: `{ tag, branch, commit }` → returns runId |
| POST | `/sdk/runs/:id/report` | External runner posts step outcomes |
| POST | `/sdk/runs/:id/complete` | Finalize |

### 3.14 LLM configuration

Workspace-scoped LLM provider config. Secrets stored AES-GCM encrypted ([DATA_MODEL.md §12](./DATA_MODEL.md#12-encryption-aes-gcm)); API never returns plaintext keys.

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/workspaces/:id/llm-config` | Current config (key redacted as `sk-****`) |
| PUT | `/workspaces/:id/llm-config` | Set/rotate provider + key (write-only key) |
| POST | `/workspaces/:id/llm-config/test` | LiteLLM `health_check` round-trip |
| DELETE | `/workspaces/:id/llm-config` | Clear config; tier downgrades to ZERO at next capability refresh |
| GET | `/workspaces/:id/llm-config/models` | List available models for the configured provider (used by Settings → LLM model dropdown) |

**GET `/workspaces/:id/llm-config/models` response.** Returns array of model metadata for the workspace's currently-configured provider. Backed by LiteLLM `litellm.model_list` for providers that expose it, otherwise a hard-coded provider catalog shipped in `packages/agent/providers/model_catalog.py`. Empty array if tier=`ZERO` (no provider configured).

```json
{
  "provider": "anthropic",
  "models": [
    {
      "id": "claude-sonnet-4-5-20250929",
      "name": "Claude Sonnet 4.5",
      "contextWindow": 200000,
      "maxOutput": 8192,
      "pricing": { "input_per_1m_usd": 3.00, "output_per_1m_usd": 15.00 }
    },
    {
      "id": "claude-haiku-4-5",
      "name": "Claude Haiku 4.5",
      "contextWindow": 200000,
      "maxOutput": 8192,
      "pricing": { "input_per_1m_usd": 0.80, "output_per_1m_usd": 4.00 }
    }
  ]
}
```

**PUT `/workspaces/:id/llm-config`** body:
```json
{
  "provider": "anthropic",      // anthropic | openai | gemini | groq | openrouter | ollama | llamacpp | vllm | lmstudio | …
  "model": "claude-sonnet-4-5-20250929",
  "apiKey": "sk-ant-…",         // write-only; never returned
  "config": {                    // optional, provider-specific
    "baseUrl": "https://api.anthropic.com",
    "timeoutMs": 60000,
    "conversation_model": "claude-haiku-4-5"   // optional override for CONVERSATION mode; defaults to provider's smallest model (e.g. claude-haiku-4-5, gpt-4o-mini). Other modes use top-level `model`.
  }
}
```

> `config_json.conversation_model` lets workspaces use a cheap/fast small model for the AI chat panel while keeping the heavyweight `model` for GENERATION / EXECUTION / DIAGNOSIS. When omitted, the agent resolver in `packages/agent/providers/litellm_router.py` picks the provider's smallest model from the catalog returned by `GET /llm-config/models`.

**GET response** (key redacted):
```json
{
  "id": "llmcfg_xxx",
  "provider": "anthropic",
  "model": "claude-sonnet-4-5-20250929",
  "apiKeyHint": "sk-ant-…last4",
  "config": { "baseUrl": "https://api.anthropic.com", "timeoutMs": 60000 },
  "isActive": true,
  "lastValidatedAt": "2026-05-26T07:11:00Z",
  "createdAt": "...",
  "updatedAt": "..."
}
```

**POST `/test` response:**
```json
{ "ok": true, "latencyMs": 412, "modelEcho": "claude-sonnet-4-5-20250929" }
```
or
```json
{ "ok": false, "error": { "code": "PROVIDER_AUTH", "message": "401 from anthropic.com" } }
```

Side-effects:
- `PUT` ⇒ recompute `workspace_capabilities` row (tier may flip ZERO → CLOUD/LOCAL) + emit `capability.changed` WS event.
- `DELETE` ⇒ tier returns to ZERO; running agent sessions complete on current LLM, new ones rejected.

### 3.15 Autonomy

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/workspaces/:id/autonomy` | Current level + per-feature overrides |
| PUT | `/workspaces/:id/autonomy` | Set level (`manual` / `assist` / `semi_auto` / `auto`) + optional overrides |
| GET | `/workspaces/:id/autonomy/audit` | Paginated history of autonomy changes |

**GET response:**
```json
{
  "level": "assist",
  "perFeature": {
    "ai_generation": "assist",
    "ai_diagnosis": "assist",
    "defect_filing": "manual"
  },
  "tier": "CLOUD",
  "updatedAt": "2026-05-26T07:00:12Z",
  "updatedBy": "u_maya"
}
```

**PUT body:**
```json
{
  "level": "semi_auto",
  "perFeature": { "defect_filing": "auto" }
}
```

403 `AUTONOMY_LEVEL_INSUFFICIENT` is raised when downstream actions exceed the configured level. Per-feature overrides require role `ADMIN` or `OWNER`. Each change appends a row to the audit table; surfaced via `/audit`.

### 3.16 MCP Providers

Per-workspace MCP server registry. Distinct from `/integrations` — these are the runtime adapters that execute test steps. See [MCP_PLUGINS.md](./MCP_PLUGINS.md).

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/mcp/providers` | List registered MCP servers + health |
| POST | `/mcp/providers` | Register a custom MCP server (validates + discovers tools unless `validate=false`) |
| POST | `/mcp/providers/test-connection` | Dry-run connect + `tools/list` without persisting (register modal) |
| GET | `/mcp/providers/:id` | Detail (secrets redacted) |
| PATCH | `/mcp/providers/:id` | Update config / endpoint |
| DELETE | `/mcp/providers/:id` | Deregister |
| POST | `/mcp/providers/:id/health` | Force health probe (returns latest) |
| POST | `/mcp/providers/:id/invoke` | **Dev aid** — invoke an arbitrary tool to validate config (gated to `ADMIN`+) |
| GET | `/mcp/providers/:id/tools` | List tools the MCP server exposes (introspection) |
| GET | `/mcp/routing` | Current `targetKind → providerId` default mapping |
| PUT | `/mcp/routing` | Override default routing (workspace-wide) |

**POST `/mcp/providers`** body:
```json
{
  "name": "postgres-mcp-staging",
  "kind": "postgres",     // browser-use | playwright | api | postgres | kubernetes | graphql | grpc | appium | mongo | mysql | custom
  "endpoint": "stdio:///opt/mcp/postgres-mcp",
  "transport": "stdio",   // stdio | sse | ws
  "configJson": { "schema": "public", "maxConnections": 4 },
  "secretsJson": { "connectionString": "postgres://…" },
  "isDefaultForTarget": { "DATA": true }
}
```

> **M2-6 built:** `GET/POST /mcp/providers`, `GET/PATCH/DELETE /mcp/providers/:id` shipped in [`routers/mcp_providers.py`](../apps/api/src/suitest_api/routers/mcp_providers.py). `GET /mcp/providers` returns the bundled builtins (synthetic `builtin:<name>` ids, `isBundled=true`, read-only) merged on top of custom workspace rows. Write fields use camelCase aliases (`configJson` / `secretsJson` / `isDefaultForTarget`); `secretsJson` is write-only and never echoed. **M2-7 built:** `POST /mcp/providers` connects + handshakes + runs `tools/list` and persists the discovered catalog + `health_status=ok` + version pins unless `validate=false`; a failed probe returns `422 {code: MCP_REGISTRATION_FAILED}` and writes no row. `POST /mcp/providers/test-connection` does the same probe without persisting. **M2-8 built:** `POST /mcp/providers/:id/discover` re-runs `tools/list` and persists catalog + health + `last_health_at`; `POST /mcp/providers/:id/invoke` is the dev-aid tool browser path — role-gated to `ADMIN`+, audit-logged with `invocation_source=tool_browser` + `arg_hash` (raw args never stored), and rejected (409) for bundled providers. `/routing` lands in M2-9.

**GET `/mcp/providers/:id/tools` response:**
```json
{
  "providerId": "mcp_xxx",
  "tools": [
    { "name": "query", "description": "Execute read-only SQL", "inputSchema": { "$ref": "..." } },
    { "name": "exec",  "description": "Execute mutation", "inputSchema": { "$ref": "..." } }
  ],
  "discoveredAt": "2026-05-26T07:00:00Z"
}
```

**POST `/mcp/providers/:id/invoke`** (dev only, requires `ADMIN`):
```json
{ "tool": "query", "input": { "sql": "SELECT 1" } }
```

**PUT `/mcp/routing`** body (M2-9 — keys are `target_kind`, values pin a provider **by name**):
```json
{
  "overrides": {
    "BE_REST": { "primary": "api-http-mcp", "fallback": "vendor-x-http" },
    "DATA": { "primary": "mysql-mcp", "fallback": null }
  }
}
```

> **M2-9 built:** `GET /mcp/routing` returns the effective table (bundled defaults from `suitest_mcp.routing.DEFAULT_ROUTING` overlaid with workspace overrides, each row tagged `isOverride`). `PUT /mcp/routing` (ADMIN+) **replaces** the override map, validating each referenced provider name is known + enabled (else `422 MCP_PROVIDER_NOT_REGISTERED`) and each key is a valid `target_kind` (else `422 INVALID_TARGET_KIND`). Stored under `workspace_capabilities.features_json.routing_overrides` in the `{primary, fallback}` shape the runner consumes via `resolve_provider`. (The legacy `workspaces.mcp_routing_overrides` column is **not** the runtime source.)

Errors:
- `404 MCP_PROVIDER_NOT_REGISTERED` when targeting an unknown id.
- `503 MCP_PROVIDER_UNHEALTHY` when invoking against a provider whose last health probe failed.

### 3.17 Generators

Deterministic + LLM-driven test generators. Deterministic ones (`/openapi`, `/recorder`, `/crawler`, `/classify`) work in **all tiers including ZERO**.

| Method | Path | Tujuan | LLM required? |
|--------|------|--------|:-:|
| POST | `/generators/openapi` | Parse OpenAPI spec, emit per-operation cases with executable `step.code`. **(M3-8)** `options.includeLlmEdgeCases` adds AI boundary/fuzz/negative cases when an LLM is active (else skipped) | Core: No / edge: optional |
| POST | `/generators/recorder/sessions` | Start browser recorder session → returns `sessionId` + WS room | No |
| POST | `/generators/recorder/sessions/:id/finalize` | Stop recording, materialise into a test case | No |
| POST | `/generators/crawler` | Heuristic BFS crawl, fill forms with Faker, emit smoke cases | No |
| POST | `/generators/prd` | **(M3-6)** LLM extracts user stories from a PRD → DRAFT cases (agentic steps). SSE. **409 `LLM_NOT_CONFIGURED`** when no active LLM | **Yes (CLOUD/LOCAL)** |
| POST | `/generators/mcp-discovery` | **(M3-9)** LLM explores a registered MCP provider's tool catalog → DRAFT contract cases. SSE. **409** when no active LLM; **404** unknown provider; `EMPTY_CATALOG` error frame when no tools | **Yes (CLOUD/LOCAL)** |
| POST | `/generators/url-semantic` | **(M3-7)** LLM decomposes an intent ("checkout flow") on a URL → FE_WEB journey cases (playwright-mcp). SSE. **409** when no active LLM | **Yes (CLOUD/LOCAL)** |
| POST | `/generators/classify` | Utility: input → `{targetKind, recommendedMcp, recommendedStrategy}` | No |

**POST `/generators/openapi`** body:
```json
{
  "specUrl": "https://api.suitest.io/openapi.json",
  // OR "specContent": "<raw YAML/JSON>",
  "targetSuiteId": "ckxxxx",
  "options": {
    "includeNegativeAuth": true,
    "includeSchemaValidation": true,
    "tagPrefix": "api-contract"
  }
}
```
Response:
```json
{
  "generatorRunId": "gen_xxx",
  "targetSuiteId": "ckxxxx",
  "casesCreated": 47,
  "publicIds": ["TC-2001", "TC-2002", "..."],
  "durationMs": 312
}
```

**POST `/generators/recorder/sessions`** body:
```json
{
  "projectId": "ckxxxx",
  "startUrl": "https://staging.example.com",
  "mcpProvider": "playwright-mcp"
}
```
Response:
```json
{
  "sessionId": "rec_xxx",
  "wsRoom": "recorder:rec_xxx",
  "browserUrl": "http://recorder.local:9222/devtools",
  "expiresAt": "2026-05-26T08:00:00Z"
}
```

**POST `/generators/recorder/sessions/:id/finalize`** body:
```json
{
  "targetSuiteId": "ckxxxx",
  "name": "Checkout — recorded happy path",
  "priority": "P1"
}
```
Returns the generated `TestCase` (with `source: "RECORDER"`).

**POST `/generators/crawler`** body:
```json
{
  "projectId": "ckxxxx",
  "url": "https://staging.example.com",
  "depth": 3,
  "authConfig": { "kind": "form", "loginUrl": "/login", "credentials": { "u": "...", "p": "..." } },
  "targetSuiteId": "ckxxxx"
}
```

**POST `/generators/classify`** body — auto-route preview:
```json
{ "input": { "type": "url", "value": "https://api.example.com/openapi.json" } }
```
Response:
```json
{
  "targetKind": "BE_REST",
  "recommendedMcp": { "id": "mcp_xxx", "name": "api-mcp" },
  "recommendedStrategy": "openapi-generator",
  "alternatives": [
    { "strategy": "url-semantic", "requiresTier": "CLOUD" }
  ]
}
```

### 3.18 Code Export

Export a test case to runnable code in a target framework. Always available (no LLM required for the export itself — it walks `step.code`).

| Method | Path | Tujuan |
|--------|------|--------|
| GET | `/test-cases/:id/export?target=playwright` | Return generated code (text/plain) + `Content-Disposition: attachment` |

Supported `target` values: `playwright` (default), `cypress`, `selenium`.

Response (200):
```
Content-Type: text/plain; charset=utf-8
Content-Disposition: attachment; filename="TC-1045.spec.ts"

import { test, expect } from '@playwright/test';

test('Login with valid credentials', async ({ page }) => {
  await page.goto('/login');
  ...
});
```

A row is written to `code_exports` for audit.

### 3.19 Eval (v1.x — backend ships in v1.0, no UI yet)

| Method | Path | Tujuan |
|--------|------|--------|
| POST | `/eval/runs` | Kick off an eval suite (gated to `ADMIN`+, CLOUD/LOCAL only) |
| GET | `/eval/runs/:id` | Results |

**POST body:**
```json
{
  "evalSuiteName": "generate-from-prd-v1",
  "promptVersionId": "pv_xxx",
  "model": "claude-sonnet-4-5-20250929",
  "fixturesPath": "evals/fixtures/prd-001/"
}
```
**GET response:**
```json
{
  "id": "eval_xxx",
  "evalSuiteName": "generate-from-prd-v1",
  "fixturesCount": 25,
  "passed": 23,
  "failed": 2,
  "model": "claude-sonnet-4-5-20250929",
  "promptVersionId": "pv_xxx",
  "results": [
    { "fixture": "checkout-001", "passed": true, "score": 0.94 },
    { "fixture": "checkout-002", "passed": false, "reason": "missed edge case 'sold-out'" }
  ],
  "runAt": "2026-05-26T08:11:00Z"
}
```

---

## 4. WebSocket events

Path: `/ws`, **native FastAPI WebSocket** (no Socket.io). Auth via `?token=<bearer>` query string or `Authorization` header during the HTTP upgrade.

Setelah connect, client join rooms via the explicit `subscribe.*` events below:
- `workspace:<wsId>` — global notifs (defect filed, integration error, capability/MCP changes)
- `run:<runId>` — live updates untuk specific run
- `agent-session:<sessionId>` — message streaming
- `recorder:<sessionId>` — live preview of recorder-captured steps

Wire format: each frame is a JSON envelope `{"type": "<event>", "data": {...}}` — keeps it Socket.io-compatible on the client side without the Socket.io protocol.

### Server → client events

| Event | Payload | Trigger |
|-------|---------|---------|
| `run.queued` | `{ runId, position }` | Run enters queue |
| `run.started` | `{ runId, startedAt, tier, mcpSession }` | Worker pick up |
| `run.step.started` | `{ runId, stepIndex, action, mcpProvider, targetKind }` | Step begin |
| `run.step.log` | `{ runId, stepIndex, level, message, time }` | Streaming log line |
| `run.step.completed` | `{ runId, stepIndex, outcome, durationMs, artifacts }` | Step done |
| `run.completed` | `{ runId, status, summary }` | Run done |
| `defect.created` | `{ defectId, severity, testCaseId, runId, diagnosisKind }` | Auto-file |
| `defect.updated` | `{ defect: DefectRead }` | Status / severity / assignee edit. Room: `workspace:<wsId>` |
| `case.created` | `{ case: TestCaseRead }` | TC successfully created. Room: `workspace:<wsId>` |
| `case.updated` | `{ case: TestCaseRead }` | Metadata / tag patch on TC. Room: `workspace:<wsId>` |
| `case.steps.replaced` | `{ case_id, step_count }` | Atomic step replace (`PATCH /test-cases/:id/steps` or `/steps/reorder`). Room: `workspace:<wsId>` |
| `integration.error` | `{ integration_id, kind, error_code, message }` | Adapter or webhook receiver fails (replaces `integration.status` for hard errors). Room: `workspace:<wsId>` |
| `agent.message.delta` | `{ sessionId, role, contentDelta }` | Token streaming |
| `agent.tool.start` | `{ sessionId, toolName, input, mcpProvider? }` | Agent invokes tool |
| `agent.tool.end` | `{ sessionId, toolName, output, durationMs }` | Tool completes |
| `agent.tool.routed` | `{ sessionId, toolName, targetKind, chosenMcpProvider, alternatives }` | **NEW** — emitted before `agent.tool.start` when the agent picks an MCP for a tool call (transparency / debug) |
| `agent.session.completed` | `{ sessionId, summary, costUsd }` | Session done |
| `integration.status` | `{ integrationId, status, error? }` | Health change |
| `mcp.provider.health` | `{ providerId, name, status, latencyMs?, error? }` | **NEW** — MCP provider health probe state change |
| `capability.changed` | `{ tier, autonomy, provider?, model?, embeddings, mcpProviderCount }` | **NEW** — broadcast to `workspace:<wsId>` on tier/autonomy/LLM-config/MCP changes |
| `generator.recorder.step` | `{ sessionId, stepIndex, action, selector, url, screenshotUrl? }` | **NEW** — live preview: recorder just captured a step |

### Client → server events

| Event | Payload | Tujuan |
|-------|---------|--------|
| `subscribe.workspace` | `{ wsId }` | Join workspace room (capability / MCP / defect notifs) |
| `subscribe.run` | `{ runId }` | Join run room |
| `unsubscribe.run` | `{ runId }` | Leave run room |
| `subscribe.recorder` | `{ sessionId }` | Join recorder live-preview room |
| `agent.cancel` | `{ sessionId }` | Stop agent mid-generation |

---

## 5. Rate limits

| Audience | Limit |
|----------|-------|
| Web user (session cookie) | 600 req/min |
| API token | 1000 req/min |
| Webhooks | unlimited tapi signature required |
| Agent endpoints | 60 req/min per workspace |
| Generation specifically (LLM) | 20 req/min per workspace |

`429` response includes `Retry-After` header dalam detik.

**Per-tier note.**

- **ZERO** — there are no LLM endpoints to limit. Deterministic generator endpoints (`/generators/openapi`, `/generators/recorder/*`, `/generators/crawler`, `/generators/classify`) share the regular API budget.
- **LOCAL** — local provider (Ollama / llama.cpp / vLLM) RPM is bounded by the model server's own concurrency; Suitest does not impose an extra LLM-side limit beyond the workspace cap.
- **CLOUD** — LiteLLM enforces the upstream provider's RPM/TPM. Suitest tracks remaining budget per `(workspace_id, provider, model)` and returns `429` with `Retry-After` derived from upstream `retry-after` headers when possible.
- All generation endpoints (`/agent/generate/cases`, `/agent/diagnose/*`, `/agent/suggest/*`) **share a single LiteLLM rate-limit budget** per workspace — a burst of generation throttles diagnosis and vice-versa. Budgets configurable via `SUITEST_LLM_RPM_LIMIT` env.

---

## 6. SDKs

**Targeted M4:**

- `suitest-py` — Python SDK, generated dari OpenAPI via `openapi-python-client`. Primary SDK (matches backend language; used by CI tooling and the CLI internally).
- `@suitest/sdk` — TypeScript SDK, generated via `openapi-typescript-codegen`. Kept for browser/Node integration users.
- `suitest` — CLI, single Python entrypoint installed via [`uv`](https://github.com/astral-sh/uv): `uv tool install suitest`, then `suitest run --suite smoke --branch main`.

**Python (primary):**

```python
from suitest import SuitestClient

suitest = SuitestClient(api_key=os.environ["SUITEST_TOKEN"])

run = suitest.runs.start(
    project_id="prj_xxx",
    selection={"type": "tag", "tags": ["smoke"]},
    branch="main",
)

async for event in suitest.runs.watch(run.id):
    print(event.type, event.payload)
```

**TypeScript (browser/Node):**

```ts
import { SuitestClient } from '@suitest/sdk';

const suitest = new SuitestClient({ apiKey: process.env.SUITEST_TOKEN });

const run = await suitest.runs.start({
  projectId: 'prj_xxx',
  selection: { type: 'tag', tags: ['smoke'] },
  branch: 'main',
});

for await (const event of suitest.runs.watch(run.id)) {
  console.log(event.type, event.payload);
}
```

---

## 7. OpenAPI generation

FastAPI generates **OpenAPI 3.1** automatically at `GET /openapi.json` (with Swagger UI at `/docs`, ReDoc at `/redoc`). Pydantic v2 schemas drive both runtime request/response validation **and** the OpenAPI document — there is no separate schema language.

SDK codegen pipeline:

- Python SDK (`suitest-py`) → generated via [`openapi-python-client`](https://github.com/openapi-generators/openapi-python-client)
- TS SDK (`@suitest/sdk`) → generated via [`openapi-typescript-codegen`](https://github.com/ferdikoomen/openapi-typescript-codegen)

Build artifact `openapi.json` is committed to `packages/shared/openapi.json` on every release so SDK codegen is reproducible from a tag.

---

## 8. Aturan saat tambah endpoint baru

1. **Tulis Pydantic schema dulu** di `packages/shared/schemas/<resource>.py` (request + response models, with `model_config = ConfigDict(from_attributes=True)`)
2. **Tambahkan tabel di doc ini** (section 3) — termasuk error codes baru di §2.1 kalau ada
3. **Implement handler** di `apps/api/src/routes/<resource>.py` pakai FastAPI `APIRouter`, register di `apps/api/src/main.py`. Wajib `Depends(require_tier(...))` kalau endpoint LLM-dependent
4. **Tulis pytest** di `apps/api/tests/test_<resource>.py` (pytest-asyncio strict) — minimum: happy path + 1 error path + 1 tier-gating path kalau relevan
5. **Update SDKs** (regenerate dari `openapi.json` — `make sdk` di repo root regen kedua-duanya)
6. **PR** dengan doc diff + Alembic migration kalau menyentuh schema
