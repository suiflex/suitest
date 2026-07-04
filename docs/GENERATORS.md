# docs/GENERATORS.md

> Specification for test case generation in Suitest. Generators fall into two families: **deterministic** (works on every tier, including ZERO) and **LLM-driven** (CLOUD/LOCAL only). Both plug into the MCP routing layer ([MCP_PLUGINS.md](./MCP_PLUGINS.md)) so their output is compatible with the runner.

> 🚧 **SPEC — partially built.** Deterministic generators (M2-1..4) live on branch `feat/m2-generators-mcp`, NOT merged to main. LLM-driven generators target M3. Nothing generator-related on current main tree. See [ROADMAP.md](./ROADMAP.md) M2/M3.
>
> Cross-refs: [AI_AGENT.md](./AI_AGENT.md), [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md), [AUTONOMY.md](./AUTONOMY.md), [MCP_PLUGINS.md](./MCP_PLUGINS.md), [DATA_MODEL.md](./DATA_MODEL.md), [API.md](./API.md).

---

## 1. Concept

Generator = "given some input, produce N test cases ready to run". Generation pipeline:

```
       input (URL, file, text, ...)
              │
              ↓
       target.classify   ← deterministic, rule-based
              │
              ↓
       resolve MCP provider for target  ← from /mcp/providers default mapping
              │
              ↓
       choose generator strategy
       ├── deterministic only (ZERO compatible)
       ├── deterministic + AI enrich (hybrid)
       └── AI-only (CLOUD/LOCAL)
              │
              ↓
       produce cases (with step.code where possible)
              │
              ↓
       persist as DRAFT (status depends on autonomy — see AUTONOMY.md § 3)
              │
              ↓
       user reviews in UI, approves → ACTIVE
```

Every generated case carries:

- `generated_from` — source provenance (`OPENAPI` | `RECORDER` | `CRAWLER` | `PRD` | `URL_SEMANTIC` | `MCP_DISCOVERY` | `OPENAPI_ENRICH`)
- `target_kind` — classifier output (`BE_REST` | `BE_GRAPHQL` | `BE_GRPC` | `FE_WEB` | `FE_MOBILE` | `DATA` | `INFRA` | `MIXED` | `CUSTOM`)
- `mcp_provider` — per-step (`step.mcp_provider`) so a single case can mix providers
- `status` — `DRAFT` by default (autonomy-overrideable to `ACTIVE`; see [AUTONOMY.md](./AUTONOMY.md))

---

## 2. Target classification (deterministic)

Pre-step before generation. Sniffs the input and decides which target kind we're testing. No LLM involved. Lives in `packages/agent/suitest_agent/tools/target.py` (also exposed to the LLM as a tool — see [AI_AGENT.md § 7](./AI_AGENT.md)).

```python
# packages/agent/suitest_agent/tools/target.py
from enum import Enum
import re
from pydantic import BaseModel

class TargetKind(str, Enum):
    BE_REST     = "BE_REST"
    BE_GRAPHQL  = "BE_GRAPHQL"
    BE_GRPC     = "BE_GRPC"
    FE_WEB      = "FE_WEB"
    FE_MOBILE   = "FE_MOBILE"
    DATA        = "DATA"
    INFRA       = "INFRA"
    MIXED       = "MIXED"
    CUSTOM      = "CUSTOM"

class GenerationInput(BaseModel):
    url: str | None = None
    content_type: str | None = None
    filename: str | None = None
    body: str | None = None      # raw text / yaml / json blob

def classify(inp: GenerationInput) -> TargetKind:
    """Rule-based classifier. First match wins."""
    # URL sniffs
    if inp.url:
        if inp.url.endswith(("/openapi.json", "/openapi.yaml", "/swagger.json")):
            return TargetKind.BE_REST
        if "graphql" in inp.url.lower():
            return TargetKind.BE_GRAPHQL
        if inp.url.startswith(("postgresql://", "mysql://", "mongodb://")):
            return TargetKind.DATA
    # filename sniffs
    if inp.filename:
        low = inp.filename.lower()
        if low.endswith(".graphql"): return TargetKind.BE_GRAPHQL
        if low.endswith(".proto"):   return TargetKind.BE_GRPC
        if low.endswith((".apk", ".ipa")): return TargetKind.FE_MOBILE
    # content sniffs
    if inp.body:
        try:
            j = json.loads(inp.body)
            if isinstance(j, dict) and "openapi" in j: return TargetKind.BE_REST
            if isinstance(j, dict) and j.get("kind") == "Service" and "spec" in j:
                return TargetKind.INFRA
        except Exception:
            pass
        if re.search(r"^kind:\s*(Deployment|Service|StatefulSet|DaemonSet|Ingress|ConfigMap)\b",
                     inp.body, re.M):
            return TargetKind.INFRA
    # content-type
    if inp.content_type:
        if inp.content_type.startswith("text/html"):     return TargetKind.FE_WEB
        if inp.content_type.startswith("text/markdown"): return TargetKind.MIXED
        if inp.content_type.startswith("text/plain"):    return TargetKind.MIXED
    return TargetKind.CUSTOM
```

### Full rule table

| Sniff signal | Decision |
|--------------|----------|
| URL ends `/openapi.json` or `/openapi.yaml` or `/swagger.json` | `BE_REST` |
| JSON body has `openapi:` field | `BE_REST` |
| URL contains `graphql` OR filename `*.graphql` OR GraphQL introspection 200 | `BE_GRAPHQL` |
| Filename `*.proto` | `BE_GRPC` |
| Content-Type `text/html` | `FE_WEB` |
| Filename `*.apk`, `*.ipa` | `FE_MOBILE` |
| URL scheme `postgresql://`, `mysql://`, `mongodb://` | `DATA` |
| YAML/JSON top-level `kind: {Deployment, Service, StatefulSet, DaemonSet, Ingress, ConfigMap, Job, CronJob}` | `INFRA` |
| Content-Type `text/markdown` or `text/plain` (free-form requirement) | `MIXED` |
| Everything else | `CUSTOM` |

Classifier is **always** the first step; LLM-driven generators call it too (via `target.classify` tool) so behavior stays consistent.

Override: callers can supply `target_kind` explicitly in `POST /agent/generate/cases` or `POST /generators/classify` to bypass.

---

## 3. MCP routing per target

Each target kind has a default MCP provider. Workspaces can override. See [MCP_PLUGINS.md](./MCP_PLUGINS.md) for the full provider catalog + registration flow.

| Target | Default MCP provider | Step kind |
|--------|---------------------|-----------|
| `BE_REST` | `api-mcp` | `mcp.api.request` |
| `BE_GRAPHQL` | `graphql-mcp` | `mcp.graphql.query` / `mutation` |
| `BE_GRPC` | `grpc-mcp` | `mcp.grpc.call` |
| `FE_WEB` | `playwright-mcp` (recorder + crawler) / `browser-use-mcp` (semantic) | `mcp.browser.*` |
| `FE_MOBILE` | `appium-mcp` (v2.x) | `mcp.mobile.*` |
| `DATA` | `postgres-mcp` / `mysql-mcp` / `mongo-mcp` (by URL scheme) | `mcp.db.query` / `seed` |
| `INFRA` | `kubernetes-mcp` | `mcp.k8s.apply` / `get` |
| `MIXED` | resolved per-step | varies |
| `CUSTOM` | user-provided MCP endpoint | varies |

Per-workspace override stored in `WorkspaceSetting.mcp_target_map` (JSONB), shape `{"FE_WEB": "browser-use-mcp", ...}`.

---

## 4. Deterministic generators (ZERO tier capable)

All three run with **zero LLM calls**. Output is `DRAFT` test cases with concrete `step.code`.

### 4.1 OpenAPI generator

- **Endpoint**: `POST /generators/openapi`
- **target_kind**: `BE_REST`
- **mcp_provider**: `api-mcp`
- **Input**:
  ```json
  {
    "spec_url": "https://api.acme.dev/openapi.json",
    "spec_content": null,
    "tags_filter": ["users", "orders"],
    "auth_profile_id": "auth_42"
  }
  ```
- **Stack**: `openapi-pydantic` to parse + validate spec.

**Algorithm (per operation):**

```
for op in spec.paths.*.{get,post,put,patch,delete}:
   1. contract_test:
        request: build with default values from schema examples (or Faker by type)
        assert:  status code matches spec response definition
                 response body validates against response schema (jsonschema)
   2. auth_negative_test (if op.security present):
        - missing token → expect 401/403
        - invalid token "Bearer xxxx" → expect 401/403
   3. required_field_tests (one per required field):
        for each required field in request body schema:
          omit field → expect 4xx (typically 400 or 422)
   4. boundary_tests:
        for each schema field with min/max constraints:
          int field: send min-1 and max+1 → expect 4xx
          string field: send "" if minLength≥1, send "x"*(maxLength+1) → expect 4xx
   5. rate_limit_test (if x-ratelimit-* headers documented):
        burst (limit+1 requests) → expect 429 after threshold
```

**Output**: 5–20 test cases per operation. Each step uses `mcp.api.request`:

```yaml
- mcp_provider: api-mcp
  action: "POST /users with valid payload"
  expected: "201 Created and response matches User schema"
  code: |
    response = await mcp.api.request(
      method="POST",
      url="{{base_url}}/users",
      headers={"Authorization": "Bearer {{auth.token}}"},
      body={"email": "test+{{uuid}}@example.com", "name": "Test User"},
    )
    assert response.status == 201
    assert validate_jsonschema(response.body, User_schema)
```

Quality benchmark: ≥ 95% of generated cases run green against a conformant API without manual editing.

### 4.2 Browser Recorder

- **Endpoint**: `POST /generators/recorder/sessions` (start) + `POST /generators/recorder/sessions/:id/finalize` (stop + emit case)
- **target_kind**: `FE_WEB`
- **mcp_provider**: `playwright-mcp` (default) or `browser-use-mcp` (user picks per session)

**Flow:**

```
1. User clicks "Record" in UI, picks starting URL + browser MCP provider
2. POST /generators/recorder/sessions → returns session_id + WS room
3. Backend opens MCP browser, calls mcp.browser.start_recording(session_id)
4. WS streams live preview frames + captured events to frontend
5. User demos manually: clicks, types, navigates
6. Recorder captures:
   - mcp.browser.navigate(url) on URL change
   - mcp.browser.click(selector) on click
   - mcp.browser.type(selector, text) on input (text masked if `<input type="password">`)
   - network requests (interesting ones: POST/PUT/DELETE, or 4xx/5xx)
   - assertions on visible text (user can click "Assert this text" overlay)
7. User clicks "Stop" → POST /generators/recorder/sessions/:id/finalize
8. Backend converts captured events into test case with one step per action
9. Returns DRAFT test case for user review
```

**Output**: one test case, N steps (one per captured action). Example step:

```yaml
- mcp_provider: playwright-mcp
  action: "Click 'Sign in' button"
  expected: "Login modal appears"
  code: |
    await mcp.browser.click('button[data-test="signin"]')
    await mcp.browser.wait_for('[role="dialog"][aria-label="Sign in"]', timeout_ms=3000)
```

User can edit any step before saving. Lifecycle stored in `recorder_sessions` table (active for max 30 min, then auto-finalized).

Quality benchmark: ≥ 90% of recorded cases run green on replay against the same app version.

### 4.3 Heuristic URL crawler

- **Endpoint**: `POST /generators/crawler`
- **target_kind**: `FE_WEB`
- **mcp_provider**: `playwright-mcp`

**Input:**

```json
{
  "start_url": "https://app.acme.dev",
  "max_depth": 2,
  "max_pages": 20,
  "same_origin_only": true,
  "auth": {
    "profile_id": "auth_42",
    "login_steps": [...]
  }
}
```

**Algorithm:**

```
queue = [start_url]
visited = set()
while queue and len(visited) < max_pages:
   url = queue.pop()
   if url in visited or depth(url) > max_depth: continue
   visited.add(url)
   await mcp.browser.navigate(url)

   # smoke assertion: page loaded, no console error
   console = await mcp.browser.get_console_log()
   case_smoke = TestCase(
     name=f"smoke: {url} loads without errors",
     steps=[
       Step(action=f"navigate to {url}", code=f"await mcp.browser.navigate('{url}')"),
       Step(action="no console errors", code="assert not any(l.level=='error' for l in console)"),
     ],
   )
   emit(case_smoke)

   # detect interactive elements
   elements = await mcp.browser.eval("...")  # buttons, links, forms

   # for each form: fill with Faker, submit, capture outcome
   for form in elements.forms:
     case_form = TestCase(
       name=f"form: {form.id or form.action} submits",
       steps=[
         Step(action=f"navigate to {url}", code=...),
         *[Step(action=f"fill {field.name}", code=f"await mcp.browser.type('{field.selector}', '{faker(field.type)}')")
           for field in form.fields],
         Step(action="submit", code=f"await mcp.browser.click('{form.submit_selector}')"),
         Step(action="expect success indicator", code="..."),
       ],
     )
     emit(case_form)

   # enqueue same-origin links
   for link in elements.links:
     if same_origin(link.href, start_url): queue.append(link.href)
```

Faker locale picked from workspace setting (`en_US` default; supports `id_ID`, `ja_JP`, etc).

**Output**: skeleton cases per discovered flow.

Quality note: this is **smoke-test grade**. The crawler doesn't understand intent — a form labeled "Subscribe to newsletter" will be filled with random Faker email and submitted regardless of business meaning. Cases need human curation before being trusted. Quality benchmark: ≥ 70% of generated cases run green; the rest are good starting skeletons.

---

## 5. LLM-driven generators (CLOUD/LOCAL only)

All require `tier ∈ {CLOUD, LOCAL}`. Return `503 LLM_DISABLED` in ZERO. Driven by LangGraph state machines defined in `packages/agent/suitest_agent/graphs/` ([AI_AGENT.md § 4](./AI_AGENT.md)).

### 5.1 PRD natural language

- **Endpoint**: `POST /agent/generate/cases` with `source: "PRD"`
- **target_kind**: `MIXED` (LangGraph decomposes into sub-targets per story)
- **Graph**: `graphs/generate_from_prd.py`
- **Tools used**: `docs.read`, `search.suite`, `target.classify`, `cases.create`

User uploads PRD text/markdown. Agent:

1. Chunks input, retrieves related context from prior PRDs.
2. Extracts user stories + acceptance criteria.
3. For each story: calls `target.classify` to decide which target this story tests (a checkout story might decompose into `BE_REST` + `FE_WEB` sub-cases).
4. Drafts happy path + 1–3 edge variants per story.
5. Streams cases via SSE.

See [AI_AGENT.md § 8.1](./AI_AGENT.md) for the prompt + node diagram.

### 5.2 URL semantic (browser-use AI)

- **Endpoint**: `POST /agent/generate/cases` with `source: "URL_SEMANTIC"`
- **target_kind**: `FE_WEB`
- **mcp_provider**: `browser-use-mcp` (semantic-aware) — overridable
- **Graph**: `graphs/generate_from_url_semantic.py`
- **Stack**: `browser-use` Python library wraps the MCP browser, exposing semantic primitives ("find checkout flow", "find login").

User supplies a URL + optional intent hints ("test the signup + onboarding journey"). Agent runs an exploratory loop:

1. Launch browser MCP, navigate to URL.
2. Snapshot DOM + identify candidate flows (forms, multi-step modals, nav menus).
3. For each flow, drive an agentic exploration run to observe success criteria.
4. Draft a case per discovered flow using observed selectors + outcomes.

Slowest mode (10–30 s/case). UI shows per-case progress.

### 5.3 MCP tool discovery

- **Endpoint**: `POST /agent/generate/cases` with `source: "MCP_DISCOVERY"`
- **target_kind**: `CUSTOM`
- **Graph**: `graphs/generate_from_mcp_discovery.py` (single node + tool loop)

User registers a custom MCP server (`POST /mcp/providers`) and triggers discovery. Agent:

1. Calls `mcp.discover_tools(provider_id)` → gets list of tool names + descriptions + input schemas.
2. For each tool, plans valid + invalid invocations.
3. Generates test cases that exercise each tool path.

Useful for testing in-house MCP servers (e.g., a custom `payments-mcp` exposing `mcp.payments.charge`, `mcp.payments.refund`).

### 5.4 OpenAPI enrich (hybrid)

- **Endpoint**: `POST /generators/openapi?enrich=true` (or `POST /agent/generate/cases` with `source: "OPENAPI_ENRICH"`)
- **target_kind**: `BE_REST`
- **mcp_provider**: `api-mcp`
- **Graph**: `graphs/generate_from_openapi_ai.py`

Hybrid: deterministic baseline + AI top-up.

1. Run § 4.1 deterministic generator → N baseline cases.
2. For each operation, agent receives operation summary, description, examples, schema → proposes additional edge cases not derivable from rules alone (semantically unusual inputs, business-rule violations gleaned from the description).
3. Merge + dedupe (Levenshtein on case name + step signatures; threshold 0.85).
4. User reviews the merged set, can accept/reject AI suggestions individually.

If LLM call fails or times out, fall back to deterministic-only output with a warning event.

---

## 6. Per-tier availability matrix

| Generator | ZERO | LOCAL | CLOUD |
|-----------|:----:|:-----:|:-----:|
| OpenAPI (§ 4.1) | yes | yes | yes |
| Browser Recorder (§ 4.2) | yes | yes | yes |
| Heuristic crawler (§ 4.3) | yes | yes | yes |
| PRD natural language (§ 5.1) | no (503) | yes | yes |
| URL semantic (§ 5.2) | no (503) | yes | yes |
| MCP discovery (§ 5.3) | no (503) | yes | yes |
| OpenAPI enrich (§ 5.4) | no (auto-degrades to § 4.1) | yes | yes |

In ZERO, `POST /agent/generate/cases` returns:

```json
HTTP 503
{
  "code": "LLM_DISABLED",
  "message": "AI generation requires LLM provider configuration.",
  "hint": "Use deterministic generators: POST /generators/openapi, /generators/recorder/sessions, /generators/crawler",
  "available_alternatives": ["openapi", "recorder", "crawler"]
}
```

---

## 7. API endpoints

Cross-link: [API.md](./API.md). Summary:

| Method | Path | Purpose | Tier requirement |
|--------|------|---------|------------------|
| `POST` | `/generators/classify` | Run target classifier on input | ZERO |
| `POST` | `/generators/openapi` | Deterministic OpenAPI generation | ZERO |
| `POST` | `/generators/recorder/sessions` | Start recorder session | ZERO |
| `WS` | `/generators/recorder/sessions/:id/stream` | Live preview + event capture | ZERO |
| `POST` | `/generators/recorder/sessions/:id/finalize` | Stop + emit case | ZERO |
| `POST` | `/generators/crawler` | Run heuristic crawler | ZERO |
| `POST` | `/agent/generate/cases` | LLM-driven; body: `source` ∈ {PRD, URL_SEMANTIC, MCP_DISCOVERY, OPENAPI_ENRICH} | LOCAL or CLOUD |
| `GET` | `/agent/sessions/:id/stream` | SSE events for any AI generation | LOCAL or CLOUD |
| `GET` | `/test-cases/:id/export?target=playwright\|cypress\|selenium` | Code export of an existing case | ZERO |

All generators write to `test_cases` with `status=DRAFT` by default; final status depends on autonomy (see [AUTONOMY.md § 3](./AUTONOMY.md), key `gen_create_status`).

---

## 8. UI flow

The generation modal in the Suite page is a 5-step wizard:

```
Step 1: "What are you testing?"
  ◯ Backend (REST / GraphQL / gRPC)
  ◯ Frontend (Web)
  ◯ Mobile           [v2.x]
  ◯ Data (DB)
  ◯ Infrastructure   [v1.x]
  ◯ Mixed (PRD → multiple)
  ◯ Custom (MCP)

Step 2: Source input
  - if Backend: OpenAPI URL / spec file / GraphQL endpoint URL / .proto file
  - if Frontend: start URL + auth profile
  - if Mixed: paste PRD / upload markdown
  - if Custom: MCP provider picker
  (Step 1 + 2 combined drives target.classify; result shown back to user for confirmation)

Step 3: MCP provider
  Default for target shown pre-selected.
  "Use different MCP provider for this target?" → dropdown of registered providers.
  Link: "Manage MCP providers" → /integrations/mcp.

Step 4: Strategy
  ◯ Deterministic only (ZERO compatible; works without LLM)
  ◯ Deterministic + AI enrich (recommended; hybrid)        [LLM required]
  ◯ AI-only (PRD-style; semantic)                           [LLM required]
  Disabled options show tooltip "Requires LLM provider — configure in Settings → LLM".

Step 5: Review
  Streaming preview of generated cases (SSE).
  Per-case checkboxes (default checked).
  Inline edit (name, steps).
  Bottom action: [ Add N cases to suite ]  → POST to /test-cases (batch).
```


---

## 9. Mixed-MCP single test case example

Real-world example: e-commerce checkout E2E. Single test case, 5 steps, 3 different MCP providers.

```yaml
id: tc_checkout_happy_path
name: "Checkout: signed-in user pays for cart with valid card"
suite_id: suite_checkout
target_kind: MIXED
generated_from: PRD
priority: P0
tags: [checkout, e2e, critical-path]
status: ACTIVE

steps:
  - id: s1
    order: 1
    mcp_provider: postgres-mcp
    target_kind: DATA
    action: "Seed DB with test user + cart with 1 item"
    expected: "Rows present in users + carts + cart_items tables"
    code: |
      await mcp.db.query("""
        INSERT INTO users (id, email, password_hash)
        VALUES ('{{user_id}}', 'test+{{run_id}}@example.com', '{{hash}}')
      """)
      await mcp.db.query("""
        INSERT INTO carts (id, user_id) VALUES ('{{cart_id}}', '{{user_id}}')
      """)
      await mcp.db.query("""
        INSERT INTO cart_items (cart_id, product_id, qty, unit_price_cents)
        VALUES ('{{cart_id}}', 'prod_42', 1, 1999)
      """)

  - id: s2
    order: 2
    mcp_provider: api-mcp
    target_kind: BE_REST
    action: "Login to obtain session token"
    expected: "200 OK, token returned"
    code: |
      response = await mcp.api.request(
        method="POST",
        url="{{base_url}}/auth/login",
        body={"email": "test+{{run_id}}@example.com", "password": "{{password}}"},
      )
      assert response.status == 200
      set_var("auth_token", response.body["token"])

  - id: s3
    order: 3
    mcp_provider: playwright-mcp
    target_kind: FE_WEB
    action: "Open browser, login, navigate to checkout, fill card, submit"
    expected: "URL becomes /order/confirmation/* and order ID is visible"
    code: |
      await mcp.browser.navigate("{{app_url}}/login")
      await mcp.browser.type('input[name="email"]', "test+{{run_id}}@example.com")
      await mcp.browser.type('input[name="password"]', "{{password}}")
      await mcp.browser.click('button[type="submit"]')
      await mcp.browser.wait_for('[data-test="user-menu"]', timeout_ms=5000)
      await mcp.browser.navigate("{{app_url}}/checkout")
      await mcp.browser.type('input[name="card_number"]', "4242424242424242")
      await mcp.browser.type('input[name="card_exp"]',    "12/30")
      await mcp.browser.type('input[name="card_cvc"]',    "123")
      await mcp.browser.click('button[data-test="pay-now"]')
      await mcp.browser.wait_for('[data-test="order-id"]', timeout_ms=10000)
      order_id = await mcp.browser.eval(
        "document.querySelector('[data-test=order-id]').textContent"
      )
      set_var("order_id", order_id)

  - id: s4
    order: 4
    mcp_provider: api-mcp
    target_kind: BE_REST
    action: "Verify order via API"
    expected: "Order exists, status=PAID, total=1999"
    code: |
      response = await mcp.api.request(
        method="GET",
        url="{{base_url}}/orders/{{order_id}}",
        headers={"Authorization": "Bearer {{auth_token}}"},
      )
      assert response.status == 200
      assert response.body["status"] == "PAID"
      assert response.body["total_cents"] == 1999

  - id: s5
    order: 5
    mcp_provider: postgres-mcp
    target_kind: DATA
    action: "Verify DB state: order row + payments row + cart cleared"
    expected: "1 order row PAID, 1 payment row, 0 cart_items rows"
    code: |
      rows = await mcp.db.query(
        "SELECT status FROM orders WHERE id = '{{order_id}}'"
      )
      assert len(rows) == 1 and rows[0]["status"] == "PAID"
      payments = await mcp.db.query(
        "SELECT * FROM payments WHERE order_id = '{{order_id}}'"
      )
      assert len(payments) == 1
      cart_items = await mcp.db.query(
        "SELECT * FROM cart_items WHERE cart_id = '{{cart_id}}'"
      )
      assert len(cart_items) == 0
```

Runner pools MCP connections per provider type; concurrent steps to the same provider reuse a session. See [MCP_PLUGINS.md](./MCP_PLUGINS.md) for the pool spec.

---

## 10. Code export (separate but related)

- **Endpoint**: `GET /test-cases/:id/export?target=playwright|cypress|selenium`
- **Tool**: `case.export(case_id, target)` in [AI_AGENT.md § 7](./AI_AGENT.md)
- **Available in**: all tiers (no LLM needed; transformation is deterministic)

Each `step.code` is per-step transformed to the target framework's idiom by a per-provider adapter. Adapters live in `packages/agent/suitest_agent/exporters/`:

- `playwright.py` — emits `import { test } from "@playwright/test"` with `page.click()`, `page.fill()`, `page.goto()`. Output `.spec.ts`.
- `cypress.py` — emits `describe()` + `it()` blocks with `cy.visit()`, `cy.get().click()`, `cy.get().type()`. Output `.cy.ts`.
- `selenium.py` — emits Python with `WebDriverWait` + `expected_conditions`. Output `.py`.

Notes per target:

| Target | mcp.browser.* mapping | Limitations |
|--------|----------------------|-------------|
| `playwright` | direct (1:1) — Playwright MCP wraps Playwright | full fidelity |
| `cypress` | `mcp.browser.click()` → `cy.get(sel).click()`; async/await stripped | no cross-origin; `mcp.api.request` → `cy.request` |
| `selenium` | `mcp.browser.click()` → `driver.find_element(...).click()`; `wait_for` → `WebDriverWait(...).until(EC.presence_of_element_located(...))` | slower; explicit waits required |

Non-browser steps (`mcp.api.request`, `mcp.db.query`, etc.) export as native HTTP/DB client calls in the target language (`requests` for Python, `axios` for TS, etc.).

Code export is **lossy for mixed-MCP cases**: a Cypress export of a checkout case will inline DB seeds as `cy.task('db:seed', ...)` placeholders; user must wire the Cypress task themselves. UI shows a warning when exporting mixed-MCP cases.

---

## 11. Quality benchmarks

Tracked via the eval suite ([AI_AGENT.md § 15](./AI_AGENT.md)). Run weekly in CI against fixtures, results pushed to Prometheus.

| Generator | Metric | Target |
|-----------|--------|:------:|
| OpenAPI (§ 4.1) | % cases run green without manual edit | ≥ 95% |
| Browser Recorder (§ 4.2) | % cases run green on first replay | ≥ 90% |
| Heuristic crawler (§ 4.3) | % cases run green (smoke grade) | ≥ 70% |
| PRD (§ 5.1) | % cases structurally valid + relevant (LLM-as-judge eval) | ≥ 80% |
| URL semantic (§ 5.2) | % cases run green | ≥ 75% |
| MCP discovery (§ 5.3) | % tools exercised by ≥ 1 case | ≥ 90% |
| OpenAPI enrich (§ 5.4) | baseline preserved + N AI-added cases land in top-50% LLM-judge ranking | ≥ 95% baseline / ≥ 50% AI-added |

Regressions in benchmarks block release. The eval harness CLI is `uv run python -m suitest_agent.eval run`.

---

## 12. Extending with custom generators

Planned for v1.x (plugin SDK; see [ROADMAP.md](./ROADMAP.md)). Tentative shape:

```python
# packages/agent/suitest_agent/generators/_protocol.py
from typing import Protocol, AsyncIterator
from suitest_shared.schemas import TestCase, GenerationInput, GenerationContext

class Generator(Protocol):
    """Implement this and register via entry point `suitest.generators`."""
    name: str
    target_kinds: list[TargetKind]
    requires_tier: Tier             # min tier required

    async def generate(
        self,
        inp: GenerationInput,
        ctx: GenerationContext,
    ) -> AsyncIterator[TestCase]: ...
```

Discovery via `importlib.metadata.entry_points(group="suitest.generators")`. SDK package `suitest-sdk` (Python) will expose the `Generator` protocol + test helpers + a CLI scaffold (`suitest sdk new-generator`). Until v1.x ships, additions must live in-tree under `packages/agent/suitest_agent/generators/`.
