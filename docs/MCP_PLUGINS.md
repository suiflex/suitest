# MCP Plugins — Universal Testing Plugin Layer

> Source of truth: [design memo](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md) § 5. Cross-links: [API.md](./API.md), [DATA_MODEL.md](./DATA_MODEL.md), [GENERATORS.md](./GENERATORS.md), [AI_AGENT.md](./AI_AGENT.md), [ARCHITECTURE.md](./ARCHITECTURE.md), [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## 1. Concept

**MCP (Model Context Protocol)** is the Anthropic-originated open standard for connecting LLMs and runtimes to typed external tools. It is multi-provider, multi-transport, and language-agnostic. In Suitest, MCP is **not** a browser-automation shim — it is the **first-class plugin layer for all testing**.

Key implications:

- **Every step that touches an external system goes through an MCP server.** Browser clicks, API requests, DB queries, K8s assertions, gRPC calls — all flow through a typed tool.
- **MCP servers are first-class citizens.** They appear in the UI (Integrations → MCP Servers), in the DB (`mcp_providers` table), in the API (`/mcp/providers/*`), and in every step row (`step.mcp_provider`).
- **Each MCP server exposes typed tools** discoverable at runtime via the standard `tools/list` MCP method. Suitest persists the discovered catalog so generators, the agent, and the UI tool-browser can introspect what is available.
- **Per-step `mcp_provider` field** — a single test case can mix browser, API, DB, gRPC, K8s, and infra steps. This is the defining capability that makes Suitest **fundamentally beyond TestSprite**, which is locked to browser-and-API surfaces.
- **MCP is provider-agnostic.** Suitest uses the official `mcp` Python SDK so any MCP server (Anthropic-built, community, or user-authored) works without code changes.

Tagline (from the memo): _"MCP-native testing platform."_ Universal MCP plugins are the signature differentiator from every competitor in the matrix.

---

## 2. Architecture

The MCP layer lives in its own Python package and is consumed by both the agent (`packages/agent`) and the deterministic runner (`packages/runner`). See [ARCHITECTURE.md](./ARCHITECTURE.md) for the larger picture.

### 2.1 Package layout

```
packages/mcp/
├── pyproject.toml
└── suitest_mcp/
    ├── __init__.py
    ├── registry.py         # provider catalog, health, discovery cache
    ├── client.py           # session manager, transport (stdio/sse/ws)
    ├── routing.py          # default routing table per target_kind
    ├── invoker.py          # invoke tool with retry, telemetry, artifacts
    ├── pool.py             # connection pool, lifecycle, idle TTL eviction
    ├── providers/          # bundled provider configs (built into image)
    │   ├── playwright.py
    │   ├── browser_use.py
    │   ├── api_http.py     # generic HTTP MCP (built-in, in-process)
    │   ├── postgres.py
    │   ├── mysql.py
    │   ├── mongo.py
    │   ├── graphql.py
    │   ├── grpc.py
    │   ├── kubernetes.py
    │   ├── appium.py
    │   └── computer_use.py
    └── plugins/            # user-registered providers
                            # (loaded from mcp_providers table at startup)
```

### 2.2 Module responsibilities

| Module | Responsibility |
|--------|----------------|
| `registry.py` | Loads built-in + DB-backed providers. Exposes `get_provider(name)`, `list_providers()`, `discover_tools(provider)`. Caches discovered tool catalogs. |
| `client.py` | Wraps `mcp` Python SDK. Owns transports: stdio (subprocess), SSE (httpx), WebSocket (websockets). Handles handshake + initialize. |
| `routing.py` | Resolves `(target_kind, workspace) → provider`. Consults workspace overrides first, then global default table. |
| `invoker.py` | Single entry point `invoke(provider, tool, args, ctx)`. Retry policy, timeout, span emission, artifact capture, Redis pub/sub streaming. |
| `pool.py` | Per-provider connection pool. Lazy spawn, reuse for N requests, idle TTL, kill. Enforces per-workspace concurrency cap. |
| `providers/*.py` | Declarative config for built-in MCP servers (command, args, env, default tool catalog hint, auth shape). |
| `plugins/*.py` | Hot-loaded at startup from `mcp_providers` table. User-registered MCPs become first-class here. |

### 2.3 Connection lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│ invoker.invoke(provider="postgres-mcp", tool="query", ...)  │
└──────────────┬──────────────────────────────────────────────┘
               │
       ┌───────▼────────┐
       │ pool.acquire() │
       └───────┬────────┘
               │
        existing idle session?
         ┌─────┴─────┐
        yes          no
         │            │
         │     ┌──────▼───────┐
         │     │ spawn process │  (transport-dependent)
         │     │  + handshake  │
         │     └──────┬───────┘
         │            │
         └─────┬──────┘
               │
       ┌───────▼────────┐
       │ session.call() │
       └───────┬────────┘
               │
       ┌───────▼────────┐
       │ pool.release() │
       └───────┬────────┘
               │
        idle_ttl exceeded?
         ┌─────┴─────┐
        yes          no
         │            │
   ┌─────▼─────┐      └─→ keep alive
   │ terminate │
   └───────────┘
```

Defaults: lazy spawn, reuse up to `max_sessions=4`, idle TTL `60s`, hard `spawn_timeout=10s`.

### 2.4 Transport types

| Transport | When used | Mechanism |
|-----------|-----------|-----------|
| **stdio** | Most providers (CLI-based MCP servers). Default. | Subprocess pipes; JSON-RPC framed over stdin/stdout. |
| **SSE** | Long-running hosted MCP web servers. | HTTP + Server-Sent Events; `httpx` client. |
| **WebSocket** | Interactive / bidirectional (computer-use, custom). | `websockets` client, full duplex. |

Transport is per-provider config; the same provider can declare a fallback transport.

---

## 3. Bundled MCP providers (v1.0)

These providers ship inside the main Suitest image (see [DEPLOYMENT.md](./DEPLOYMENT.md) § air-gapped). They appear pre-registered in every workspace.

| Name | Kind | Transport | Target | Use case | Auth |
|------|------|-----------|--------|----------|------|
| `playwright-mcp` | browser | stdio (`npx @playwright/mcp`) | FE_WEB | E2E web tests, browser recorder backend | none |
| `browser-use-mcp` | browser | stdio (`python -m browser_use.mcp`) | FE_WEB | AI-driven web exploration & semantic crawling | none (LLM uses workspace LLMConfig) |
| `api-http-mcp` | http | in-process | BE_REST | Generic HTTP test calls (REST, OpenAPI) | per-test (header / OAuth) |
| `postgres-mcp` | db | stdio | DATA | DB invariants, seed, query, transactional probes | connection string |
| `mysql-mcp` | db | stdio | DATA | MySQL invariants & seeding | connection string |
| `mongo-mcp` | db | stdio | DATA | Mongo invariants & seeding | connection string |
| `graphql-mcp` | api | stdio | BE_GRAPHQL | GraphQL queries / mutations / subscriptions | bearer |
| `grpc-mcp` | api | stdio | BE_GRPC | gRPC unary + streaming tests | per-test (mTLS / metadata) |
| `kubernetes-mcp` | infra | stdio | INFRA | K8s resource assertions, port-forward, log tail | kubeconfig (mounted) |
| `appium-mcp` | mobile | stdio | FE_MOBILE | iOS / Android UI tests | appium server URL |
| `computer-use-mcp` | desktop | stdio (Anthropic computer-use) | FE_DESKTOP (v1.x preview, v2 stable) | Desktop app tests | OS-level (VNC / X11 / Wayland) |

> `api-http-mcp` runs **in-process** (same Python process as the runner). It is implemented as an MCP server with stdio transport but launched via an internal channel for zero subprocess overhead. All other built-ins spawn out-of-process for isolation.

---

## 4. Default routing table

Each `target_kind` resolves to a primary MCP plus an optional fallback. The runner consults this when `step.mcp_provider` is left blank.

| `target_kind` | Primary | Fallback |
|---------------|---------|----------|
| `BE_REST` | `api-http-mcp` | _none_ |
| `BE_GRAPHQL` | `graphql-mcp` | `api-http-mcp` (raw POST) |
| `BE_GRPC` | `grpc-mcp` | _none_ |
| `FE_WEB` | `playwright-mcp` | `browser-use-mcp` |
| `FE_MOBILE` | `appium-mcp` | _none_ |
| `DATA` | `postgres-mcp` | _user must override per workspace_ |
| `INFRA` | `kubernetes-mcp` | _none_ |
| `CUSTOM` | _user must set per step or workspace_ | _none_ |

### 4.1 Workspace override

A workspace can override the default routing table. Stored as JSONB in the `workspaces.mcp_routing_overrides` column (see [DATA_MODEL.md](./DATA_MODEL.md)).

```json
{
  "FE_WEB": {
    "primary": "browser-use-mcp",
    "fallback": "playwright-mcp"
  },
  "DATA": {
    "primary": "mysql-mcp",
    "fallback": null
  },
  "BE_REST": {
    "primary": "api-http-mcp",
    "fallback": "my-team-rest-mcp"
  }
}
```

Empty / missing keys fall back to the global table above. Validated on save: each named provider must exist and be `enabled=true`.

---

## 5. Custom MCP registration

Users register their own MCP servers without code changes.

### 5.1 UI flow

`Integrations → MCP Servers → "Add Custom MCP"` opens a modal with:

| Field | Type | Notes |
|-------|------|-------|
| `name` | text | URL-safe slug, unique per workspace |
| `kind` | text | Free-form label (e.g. `payments`, `ml-eval`, `kafka`) — informational |
| `endpoint` | text | URL (for SSE/WS) or shell command (for stdio) |
| `transport` | enum | `stdio` / `sse` / `ws` |
| `config_json` | JSON | Free-form provider config (env vars, args, headers) |
| `secrets_json` | JSON | Encrypted at rest, write-only field |
| `is_default_for_targets` | list | Optional list of `target_kind` values to auto-route to this provider |

### 5.2 API

Mirrored over REST — see [API.md](./API.md) § MCP for full schemas.

```
GET    /mcp/providers
POST   /mcp/providers
GET    /mcp/providers/:id
PATCH  /mcp/providers/:id
DELETE /mcp/providers/:id
POST   /mcp/providers/:id/health     # manual health re-check
POST   /mcp/providers/:id/discover   # re-run tools/list
POST   /mcp/providers/:id/invoke     # dev-mode only, role-gated
```

### 5.3 Validation on save

When a custom MCP is registered or edited, Suitest:

1. Spawns / connects with the supplied transport.
2. Performs the MCP `initialize` handshake.
3. Invokes the standard `tools/list` method.
4. Persists the discovered tool catalog in `mcp_providers.config_json.tools` (name + JSON schema per tool).
5. Marks `health_status = ok` and records the version string returned by the server.

If any step fails, the registration is rejected with a structured error. Secrets are never written to logs.

---

## 6. Tool invocation flow

When the runner (deterministic step) or the agent (LangGraph node) needs to invoke a tool, the flow is:

```
1. Resolve provider P:
   - if step.mcp_provider is set → use it
   - else → routing.resolve(workspace, step.target_kind) → primary
2. Acquire session S for P from pool (spawn if needed, see § 2.3).
3. If P.secrets is set:
     decrypt AES-GCM → inject into session env / handshake context
4. Build call:
     name = step.tool   (or tool inferred from step.code AST)
     args = step.arguments  (resolved against runtime context)
5. invoker.invoke(P, S, name, args, ctx):
     emit OTel span, start timer
     S.call_tool(name=name, arguments=args)
       → stream stdout/stderr → Redis pub/sub channel run:{run_id}:log
       → run:* channel fanned out to WebSocket subscribers
6. Capture artifacts:
     screenshots, HAR, logs → MinIO under runs/{run_id}/steps/{step_id}/
7. Return typed result (matches tool's JSON schema).
8. Telemetry:
     span attrs: provider, tool, duration_ms, outcome, error_code?
     metrics: mcp_invocations_total{provider,tool,outcome}
     audit row: actor, provider, tool, arg_hash, result_summary
9. Pool: mark session idle (or evict if exceeded ttl).
```

Pseudocode (Python):

```python
# packages/mcp/suitest_mcp/invoker.py

async def invoke(provider_name, tool, args, ctx) -> ToolResult:
    provider = registry.get(provider_name)
    if provider.health_status == "down":
        provider = routing.fallback_for(provider_name)
        if provider is None:
            raise McpProviderUnavailable(provider_name)

    async with pool.acquire(provider) as session:
        secrets = await secrets_store.decrypt(provider.secrets_ref)
        await session.ensure_context(secrets)

        with tracer.start_span("mcp.invoke") as span:
            span.set_attributes({
                "mcp.provider": provider.name, "mcp.tool": tool,
                "suitest.run_id": ctx.run_id, "suitest.step_id": ctx.step_id,
            })
            try:
                result = await session.call_tool(
                    name=tool, arguments=args,
                    on_progress=lambda c: redis.publish(f"run:{ctx.run_id}:log", c),
                )
                await artifacts.capture(ctx, result.artifacts)
                metrics.mcp_invocations_total.labels(
                    provider=provider.name, tool=tool, outcome="ok").inc()
                return result
            except McpError as e:
                span.record_exception(e)
                metrics.mcp_invocations_total.labels(
                    provider=provider.name, tool=tool, outcome="error").inc()
                raise
            finally:
                audit.log(actor=ctx.actor, provider=provider.name, tool=tool,
                          arg_hash=hash_args(args),
                          outcome=span.status.status_code.name)
```

---

## 7. Health & monitoring

Every provider exposes a health-check method (uniform contract: invoke `tools/list` and assert ≥1 tool returned within timeout).

| Aspect | Default |
|--------|---------|
| Probe interval | 60s background task (one ARQ scheduled job per provider) |
| Probe timeout | 5s |
| Persisted to | `mcp_providers.health_status` + `health_checked_at` |
| Status values | `ok` / `degraded` (>1s latency or partial tools) / `down` |
| Auto-disable threshold | `down` for >5 minutes → removed from active routing, fallback elevated |
| Broadcast | WebSocket event `mcp.provider.health` with `{provider, status, latency_ms}` |
| Recovery | Probe still runs while disabled; first `ok` restores routing |

Operators can also subscribe to the Prometheus `/metrics` endpoint: `mcp_provider_up{provider=…}`, `mcp_provider_probe_latency_ms{provider=…}`.

---

## 8. Connection pool tuning

Per-provider tunables (set in `mcp_providers.config_json.pool`):

| Key | Default | Notes |
|-----|---------|-------|
| `max_sessions` | `4` | Max concurrent live sessions for this provider |
| `idle_ttl` | `60s` | Idle session evicted after this duration |
| `spawn_timeout` | `10s` | Cap on handshake time |
| `max_requests_per_session` | `1000` | Recycle after N invocations (memory hygiene) |
| `kill_grace` | `3s` | SIGTERM grace before SIGKILL on shutdown |

Workspace-wide cap (defaults set per Helm values / `.env`):

```
SUITEST_MCP_WORKSPACE_MAX_SESSIONS=16
SUITEST_MCP_GLOBAL_MAX_SESSIONS=128
```

When the cap is reached, new invocations block on a fair queue (FIFO with priority for interactive UI invokes). Timeouts after `SUITEST_MCP_QUEUE_TIMEOUT=30s` with `MCP_POOL_EXHAUSTED` error.

See [DEPLOYMENT.md](./DEPLOYMENT.md) for Helm value overrides.

---

## 9. Security model

MCP plugins extend Suitest's attack surface. The security model is layered.

### 9.1 Isolation

- **Built-in MCP servers run as separate subprocesses** under the Suitest service account. The single in-process exception (`api-http-mcp`) carries no user-supplied code.
- **User-provided MCP commands run sandboxed where feasible**: gVisor in Helm production (`mcp.sandbox.runtimeClass: gvisor`), `firejail` profile in docker-compose. This is best-effort. The OSS docs warn: **trust your MCP servers** — they execute as code.
- In Kubernetes, MCP processes can be placed in a separate pod via the `mcp-runner` deployment, with NetworkPolicy enforced egress allowlist per provider.

### 9.2 Secrets

- Per-provider secrets stored AES-GCM encrypted (`mcp_providers.secrets_ref` → row in `encrypted_secrets`).
- Master key from `SUITEST_SECRET_KEY` env var (or KMS-derived in Helm via `extraEnv`).
- Secrets decrypted only at invocation time, only in memory, never logged.
- UI write-only — once saved, the cleartext is unrecoverable through the app.

### 9.3 Audit

Every tool invocation writes a row to `audit_log`:

```
actor_user_id | workspace_id | provider | tool | arg_hash (sha256) | outcome | duration_ms | run_id?
```

Argument hashes (not raw args) are stored to balance traceability and PII. Operators can enable `SUITEST_AUDIT_MCP_RAW=true` for environments where compliance requires full payloads — clearly flagged as PII-sensitive.

### 9.4 Network egress

Per-provider `network_policy` block in config:

```json
{
  "network_policy": {
    "egress_allow": ["api.stripe.com:443", "10.0.0.0/8:*"],
    "egress_default": "deny"
  }
}
```

Rendered into Kubernetes NetworkPolicy in Helm. In docker-compose, enforced via `iptables` init container (opt-in).

### 9.5 Threat model

| Threat | Mitigation |
|--------|------------|
| Malicious user-provided MCP exfiltrates secrets | Sandbox + per-provider egress allowlist + secrets scoped per provider (no cross-provider secret access) |
| MCP command injection via test args | All args serialized as JSON-RPC params; no shell interpolation by Suitest. Provider responsibility to validate args. |
| MCP impersonation (DNS / hostname spoof for SSE/WS) | Pin TLS fingerprints in `config_json.tls.pinned_sha256` when supplied |
| Resource exhaustion (fork bomb, OOM) | `max_sessions` + cgroups limits in Helm + spawn_timeout |
| Long-lived sessions accumulating PII in memory | `max_requests_per_session` recycle |
| Privilege escalation via container escape | gVisor runtimeClass + non-root UID + read-only rootfs |

---

## 10. Step-level MCP usage examples

The single-cell `step.mcp_provider` field unlocks heterogeneous cases. All YAML examples below correspond directly to `test_steps` rows (see [DATA_MODEL.md](./DATA_MODEL.md)).

### 10.1 Pure FE — login smoke

```yaml
case: User can sign in
steps:
  - { name: Open login, target_kind: FE_WEB, mcp_provider: playwright-mcp, tool: browser.navigate, arguments: { url: "{{base_url}}/login" } }
  - { name: Fill creds, mcp_provider: playwright-mcp, tool: browser.fill_form, arguments: { fields: { "#email": "{{user.email}}", "#password": "{{user.password}}" } } }
  - { name: Submit, mcp_provider: playwright-mcp, tool: browser.click, arguments: { selector: "button[type=submit]" } }
  - { name: Assert dashboard, mcp_provider: playwright-mcp, tool: browser.assert_text, arguments: { selector: "h1", contains: "Dashboard" } }
```

### 10.2 Pure BE — order API contract

```yaml
case: Create order returns 201 with order id
steps:
  - name: POST /orders
    target_kind: BE_REST
    mcp_provider: api-http-mcp
    tool: http.request
    arguments: { method: POST, url: "{{api_base}}/orders", headers: { Authorization: "Bearer {{token}}" }, json: { sku: "BOOK-01", qty: 2 } }
    assertions:
      - status_eq: 201
      - { jsonpath: "$.order_id", matches: "^ord_[a-z0-9]{12}$" }
```

### 10.3 Mixed checkout E2E — DB + API + browser

```yaml
case: Checkout creates persisted order
steps:
  - name: Seed inventory
    target_kind: DATA
    mcp_provider: postgres-mcp
    tool: db.exec
    arguments: { sql: "INSERT INTO inventory (sku, qty) VALUES ('BOOK-01', 10) ON CONFLICT (sku) DO UPDATE SET qty=10;" }

  - name: Login (API)
    target_kind: BE_REST
    mcp_provider: api-http-mcp
    tool: http.request
    arguments: { method: POST, url: "{{api_base}}/auth/login", json: { email: "{{user.email}}", password: "{{user.password}}" } }
    capture: { token: "$.access_token" }

  - name: Walk through checkout (browser)
    target_kind: FE_WEB
    mcp_provider: playwright-mcp
    tool: browser.script
    arguments:
      script: |
        await page.goto('{{base_url}}/shop');
        await page.click('text=BOOK-01');
        await page.click('text=Checkout');
        await page.fill('#card', '4242424242424242');
        await page.click('text=Pay');

  - name: Verify order via API
    mcp_provider: api-http-mcp
    tool: http.request
    arguments: { method: GET, url: "{{api_base}}/orders?latest=true", headers: { Authorization: "Bearer {{token}}" } }
    assertions: [ { jsonpath: "$.items[0].sku", equals: "BOOK-01" } ]

  - name: Verify DB state
    mcp_provider: postgres-mcp
    tool: db.query
    arguments: { sql: "SELECT qty FROM inventory WHERE sku='BOOK-01';" }
    assertions: [ { row_eq: { qty: 9 } } ]
```

### 10.4 Infra test — K8s replicas then endpoint probe

```yaml
case: Production deployment serves traffic
steps:
  - name: Assert deployment replicas
    target_kind: INFRA
    mcp_provider: kubernetes-mcp
    tool: k8s.get
    arguments: { kind: Deployment, namespace: prod, name: api }
    assertions: [ { jsonpath: "$.status.readyReplicas", gte: 3 } ]
  - name: Hit canary endpoint
    target_kind: BE_REST
    mcp_provider: api-http-mcp
    tool: http.request
    arguments: { method: GET, url: "https://api.example.com/_health" }
    assertions: [ { status_eq: 200 } ]
```

### 10.5 Mobile — Appium flow with API verification

```yaml
case: Mobile login + server-side session
steps:
  - { name: Launch app, target_kind: FE_MOBILE, mcp_provider: appium-mcp, tool: mobile.launch_app, arguments: { bundle_id: "com.example.app" } }
  - { name: Sign in, mcp_provider: appium-mcp, tool: mobile.type_text, arguments: { selector: "id=emailField", text: "{{user.email}}" } }
  - name: Verify server session
    target_kind: BE_REST
    mcp_provider: api-http-mcp
    tool: http.request
    arguments: { method: GET, url: "{{api_base}}/me", headers: { Authorization: "Bearer {{token}}" } }
    assertions: [ { jsonpath: "$.email", equals: "{{user.email}}" } ]
```

---

## 11. MCP tool browser (UI dev aid)

The MCP tool browser is the integration hub for debugging and exploring providers.

Navigation: `Integrations → MCP Servers → <provider> → Tools tab`.

| Element | Behavior |
|---------|----------|
| Provider list | Status dot (ok / degraded / down), pinned built-ins on top, custom below |
| **Tools** tab | Lists every tool discovered via `tools/list`. Expandable rows show the JSON schema (Zod-like rendering). |
| **Try it** form | Auto-generated form from the tool's input schema. User fills, clicks "Invoke". Output appears below: result panel, stderr panel, span trace link. |
| **History** sub-tab | Last 50 invocations from this provider across the workspace, filterable. |
| **Config** tab | Read-only view of config_json; secrets fields show `••••` only. |

API endpoint backing the Try-it form:

```
POST /mcp/providers/:id/invoke
{
  "tool": "db.query",
  "arguments": { "sql": "SELECT 1;" }
}
```

**Restrictions on `/invoke`:**

- Available only when `SUITEST_DEV_MODE=true` _or_ caller has role `mcp_admin`.
- Rate-limited per user (10/min default).
- Every invocation is audit-logged with `actor.invocation_source=tool_browser`.
- Never executed against `production`-tagged workspaces unless `dev_invoke_in_prod=true` flag set.

---

## 12. Routing override per test case / suite

Precedence (highest first):

1. `step.mcp_provider` — explicit per-step.
2. Suite-level override on the parent suite (`suites.mcp_routing_overrides`).
3. Workspace-level override (`workspaces.mcp_routing_overrides`).
4. Global default table from § 4.

### 12.1 Bulk replace

The test case editor exposes a "Re-route steps" action:

- Select steps (filter by current `mcp_provider` or `target_kind`).
- Pick new provider from a typeahead.
- Preview affected step count.
- Confirm → bulk UPDATE.

### 12.2 Migration helper

When a new MCP provider is registered, a background job (`mcp_migration_suggest`) scans existing cases and:

- For each step whose current provider matches the new provider's `kind` and `target_kind`, generates a **suggestion**.
- Suggestions surface in a banner: "12 existing steps could use `payments-mcp`. Review →".
- No automatic mutation — always human-approved.

---

## 13. Versioning MCP servers

Trust hinges on reproducibility. Each provider registration pins a version.

| Transport | Version pin field | Example |
|-----------|-------------------|---------|
| stdio (npm) | `command_pin` | `npx @playwright/mcp@1.42.0` |
| stdio (image) | `image_pin` | `ghcr.io/suitest/postgres-mcp:0.7.1` |
| stdio (git) | `git_ref` | `https://github.com/acme/mcp@v0.3.4` |
| SSE / WS | `version_header` | Server returns `X-MCP-Version: 2.1.0` during handshake; recorded |

Recorded into `mcp_providers.version_pin` and surfaced in every run's metadata so traces are reproducible across upgrades.

Upgrade flow:

1. Clone provider into `staging` workspace, bump pin.
2. Re-run smoke suite tagged `mcp:<provider>`.
3. Diff discovered tool catalog (`tools/list`) for breaking changes.
4. Promote pin to production workspaces.

---

## 14. Test code export reverse-routing

Test cases can be exported to standalone frameworks (`Playwright`, `Cypress`, `Selenium`). Non-browser MCP steps don't have a direct equivalent in those frameworks, so Suitest emits **adapter helpers**.

Mapping table:

| MCP provider | Playwright export | Cypress export | Selenium (JUnit) export |
|--------------|-------------------|----------------|--------------------------|
| `playwright-mcp` | Native `page.*` calls | `cy.*` equivalents | WebDriver API |
| `browser-use-mcp` | Falls back to recorded steps (Playwright) | Falls back to recorded steps (Cypress) | Falls back to recorded WebDriver script |
| `api-http-mcp` | `await request.fetch(...)` (Playwright APIRequestContext) | `cy.request(...)` | `OkHttpClient` helper |
| `postgres-mcp` | `import { Client } from 'pg'` setup/teardown helper | `cy.task('db:exec', ...)` + Node task plugin | `@BeforeAll` JDBC helper |
| `mysql-mcp` | `mysql2` helper | `cy.task('db:exec', ...)` | JDBC helper |
| `mongo-mcp` | `mongodb` helper | `cy.task('mongo:exec', ...)` | Mongo Java Driver helper |
| `graphql-mcp` | `graphql-request` | `cy.request` with GraphQL body | OkHttp + manual query |
| `grpc-mcp` | `@grpc/grpc-js` helper | `cy.task('grpc:call', ...)` | grpc-java helper |
| `kubernetes-mcp` | `@kubernetes/client-node` | `cy.task('kubectl', ...)` | `kubernetes-client/java` |
| `appium-mcp` | n/a (export blocked) | n/a | Appium Java client |
| `computer-use-mcp` | n/a (v2 only) | n/a | n/a |

The exporter writes a `helpers/` directory alongside the generated test files. Step-level comments preserve the original MCP provider name to aid round-tripping.

See [GENERATORS.md](./GENERATORS.md) § export for the full exporter pipeline.

---

## 15. Air-gapped deployment

Air-gap is a first-class constraint (see [DEPLOYMENT.md](./DEPLOYMENT.md)).

- **Bundled binaries** ship inside the main Suitest container image:
  - `playwright-mcp` (via `npx` cache pre-warmed in build)
  - `browser-use-mcp` (Python package vendored)
  - `api-http-mcp` (in-process, no external deps)
  - `postgres-mcp`, `mysql-mcp`, `mongo-mcp` (binaries pinned in image)
- **Custom MCPs** in air-gapped mode must come from a **local OCI registry / local npm registry** referenced by the registration's `image_pin` or `command_pin`.
- **No outbound calls** during normal operation. Discovery (`tools/list`) is local. Workspace must explicitly set `air_gapped=false` to allow MCPs that phone home (e.g. `browser-use-mcp` with cloud LLM).
- **Helm value** `mcp.airGapped: true` (default `false`) enforces a NetworkPolicy that drops all egress from MCP pods except DNS + Suitest internal services.

---

## 16. Future (v1.x and v2.x)

### v1.x

- **Plugin SDK** — Python entrypoint `suitest.plugins.mcp` for programmatic provider registration. Distributable as a pip package; auto-discovered at startup.
- **MCP marketplace** — curated registry hosted at `mcp.suitest.dev`, fully optional, served as static manifest JSON. Self-hosters can mirror.
- **On-demand MCP via npx** — currently we require pre-install for safety. v1.x adds an opt-in `allow_npx_on_demand=true` flag with signature verification.
- **MCP-as-code** — declare providers in a YAML/TOML file checked into the user's repo, synced into the DB on push (Git source of truth instead of UI clicks).

```yaml
# suitest.mcp.yaml
version: 1
providers:
  - name: payments-mcp
    kind: payments
    transport: stdio
    command: "node ./mcp/payments/index.js"
    is_default_for_targets: []
    network_policy:
      egress_allow: ["api.stripe.com:443"]
```

### v2.x

- **`computer-use-mcp` full support** — desktop app testing GA, with replay + screen recording artifacts.
- **MCP swarm / multi-MCP per step** — a step can fan out to multiple MCPs (e.g. assert DB state across 3 shards in parallel).
- **MCP capability negotiation** — Suitest classifier picks MCP based on advertised capabilities, not just registered `kind`.
- **MCP tracing across providers** — distributed trace continuity when one MCP invokes another (e.g. `kubernetes-mcp` triggers a probe via `api-http-mcp`).

---

_End of MCP_PLUGINS.md. For agent-side consumption of these providers, see [AI_AGENT.md](./AI_AGENT.md) § tool wiring. For the relevant DB tables, see [DATA_MODEL.md](./DATA_MODEL.md) § `mcp_providers`. For HTTP contract details, see [API.md](./API.md) § MCP endpoints._
