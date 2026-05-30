# docs/AUTONOMY.md

> Autonomy = **how much the agent does without asking the human**. Capability tier ([CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md)) = **what's available at all**. The two dimensions are orthogonal: you can be in CLOUD tier with `manual` autonomy (LLM key configured but agent forbidden from doing anything), or in LOCAL tier with `auto` autonomy (fully autonomous local Ollama).
>
> Cross-refs: [AI_AGENT.md](./AI_AGENT.md), [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md), [API.md](./API.md), [DATA_MODEL.md](./DATA_MODEL.md), [GENERATORS.md](./GENERATORS.md).

---

## 1. Concept

Two independent dimensions per workspace:

| Dimension | Source | Determines |
|-----------|--------|------------|
| **Capability tier** | Env config (`SUITEST_LLM_PROVIDER`) | What features physically exist (ZERO / LOCAL / CLOUD) |
| **Autonomy level** | Workspace setting (`AutonomyConfig.level`) | Of the features that exist, how many the agent runs without a human in the loop |

Examples:

| Tier | Autonomy | Result |
|------|----------|--------|
| ZERO | (forced `manual`) | TCM + deterministic generators + manual runs |
| CLOUD | `manual` | LLM configured but agent disabled; only deterministic + manual workflow |
| CLOUD | `assist` (default) | AI suggests, human approves each artifact |
| CLOUD | `auto` | Hands-off CI mode; agent acts, human reviews audit log |
| LOCAL | `semi_auto` | Local Ollama running self-hosted, P2/P3 auto, P0/P1 gated |

> A workspace upgrading from ZERO → CLOUD does **not** auto-upgrade autonomy. The admin must explicitly opt in. See § 8.

---

## 2. The 4 levels

| Level | When default | One-liner |
|-------|--------------|-----------|
| **`manual`** | Forced in ZERO tier. Opt-in in LOCAL/CLOUD. | No AI actions. Agent UI hidden. Pure deterministic + human workflow. |
| **`assist`** | Default when LLM available. | AI proposes; human approves every artifact and every agentic step. |
| **`semi_auto`** | Opt-in. | P2/P3 auto-approve; P0/P1 require human gate. Full agentic execution. Auto-categorize diagnoses but don't auto-close defects. |
| **`auto`** | Opt-in. Intended for production CI. | Everything auto: generation finalize, agentic execute, file defects, mark FLAKEs resolved after N green retries, optionally open fix PRs. Safety rails still enforced (§ 9). |

---

## 3. Per-feature autonomy matrix

Rows = behavior key. Columns = level. Cells = behavior when in that level.

| Feature key | `manual` | `assist` | `semi_auto` | `auto` |
|-------------|----------|----------|-------------|--------|
| **`gen_create_status`** (status of AI-generated cases) | n/a | `DRAFT` (always) | `DRAFT` if P0/P1 else `ACTIVE` | `ACTIVE` |
| **`gen_dedupe_action`** | n/a | flag, ask | flag, ask if P0/P1 | auto-merge into existing |
| **`exec_agentic_step`** | skip + warn | confirm each step via WS prompt | run without prompt | run + auto-retry once on transient error |
| **`exec_self_heal`** (v1.x) | OFF | OFF | OFF | regenerate selectors on DOM drift, 1 retry |
| **`diagnose_run_on_failure`** | OFF (rule-based fallback only) | run + human review before defect close | run + auto-categorize FLAKE/INFRA, P0/P1 stay DRAFT | run + full auto |
| **`defect_file`** | manual | AI files, human edits severity | AI files final | AI files final |
| **`defect_close_flake`** | OFF | OFF (human closes) | OFF (human closes) | mark `RESOLVED` after N green retries; human still closes |
| **`flaky_auto_rerun`** | OFF | suggest rerun | auto-rerun if FLAKE category, max 2 | auto-rerun, max 3 |
| **`code_export_on_failure`** | OFF | OFF | OFF | export `step.code` as Playwright snippet on first failure |
| **`auto_pr_fix`** (v2.x) | OFF | OFF | OFF | open PR with `suggested_fix` patch (requires `gh_app_installed`) |
| **`conversation_can_mutate`** | OFF | requires UI confirm | requires UI confirm | requires UI confirm (mutations always confirmed in chat) |
| **`upgrade_prompt_visible`** | yes | yes | no | no |

> Note on `conversation_can_mutate`: even in `auto`, chat-initiated mutations always require an explicit UI confirm. This is a hard rail to prevent prompt-injection-driven destructive actions.

---

## 4. Decision points

Every place the system makes a choice based on autonomy. UI/API surface affected listed.

| # | Decision | Affected surface |
|---|----------|------------------|
| 1 | Status on AI-generated case creation (`DRAFT` vs `ACTIVE`) | `POST /agent/generate/cases` response, Cases list filter |
| 2 | "Approve next agentic step?" prompt in execution | WS event `agent.step.confirm_required`, Run detail modal |
| 3 | Diagnosis → human-review-before-close gate | Defect detail page, `PATCH /defects/:id` rules |
| 4 | Severity override after AI categorization | Defect form, `severity_locked` flag |
| 5 | Flaky rerun threshold (`max_retries`) | Run worker config, `runs` table `retry_count` |
| 6 | Auto-merge fix PR after green | GitHub App webhook handler |
| 7 | Show "Upgrade autonomy" upsell in dashboard | `Dashboard` widget visibility |
| 8 | Auto-link defects to tracker (Jira/Linear) on creation | `tracker.create_issue` invocation in defect flow |
| 9 | Auto-export `step.code` after first agentic translate | `case.export` invocation in execution graph |
| 10 | Concurrent agent sessions allowed per workspace | Rate limiter |

---

## 5. Per-feature override

Workspace admins can flip individual feature keys even within a level. Example: workspace runs `auto` for CI but admin disables `defect_close_flake` because they want a human to always confirm fixes.

Schema:

```python
# packages/agent/suitest_agent/capabilities.py (sketch)
from enum import IntEnum
from pydantic import BaseModel, Field

class AutonomyLevel(IntEnum):
    MANUAL    = 0
    ASSIST    = 1
    SEMI_AUTO = 2
    AUTO      = 3

class AutonomyConfig(BaseModel):
    level: AutonomyLevel
    overrides: dict[str, bool] = Field(default_factory=dict)
    # `overrides` keys must be from KNOWN_OVERRIDE_KEYS; values force enable/disable
    # against the level's default behavior in the matrix above.

KNOWN_OVERRIDE_KEYS: set[str] = {
    "gen_finalize_p2p3",
    "gen_dedupe_auto_merge",
    "exec_agentic_no_prompt",
    "exec_self_heal_enabled",
    "diagnose_auto_categorize",
    "defect_auto_file",
    "defect_close_flaky",
    "flaky_auto_rerun",
    "code_export_on_failure",
    "auto_pr_fix",
}
```

### Override key reference

| Key | Default in `auto` | Effect when overridden |
|-----|:----------------:|------------------------|
| `gen_finalize_p2p3` | `true` | If `false`, all generated cases stay DRAFT regardless of priority |
| `gen_dedupe_auto_merge` | `true` | If `false`, agent flags duplicates but never auto-merges |
| `exec_agentic_no_prompt` | `true` | If `false`, even in `auto` the agent prompts before each agentic step |
| `exec_self_heal_enabled` | `true` (v1.x+) | Self-heal opt-out |
| `diagnose_auto_categorize` | `true` | If `false`, every diagnosis lands as `MANUAL_TRIAGE` |
| `defect_auto_file` | `true` | If `false`, agent only drafts the defect; human must click "File" |
| `defect_close_flaky` | `true` | If `false`, FLAKE retries don't auto-resolve |
| `flaky_auto_rerun` | `true` | If `false`, no auto-rerun on FLAKE category |
| `code_export_on_failure` | `true` | If `false`, no `step.code` artifact emitted on first run |
| `auto_pr_fix` | `false` (still opt-in even in auto, v2.x) | `true` enables PR codegen if GitHub App installed |

Resolution rule: `effective(key) = override.get(key, default_for_level(key))`. Overrides are applied **after** the level default and **before** the safety rails (§ 9) — safety rails always win.

---

## 6. API contract

Cross-link: [API.md](./API.md).

```
GET   /workspaces/:id/autonomy
PUT   /workspaces/:id/autonomy
```

### GET response

```json
{
  "level": "assist",
  "overrides": { "defect_close_flaky": false },
  "effective": {
    "gen_create_status": "DRAFT",
    "exec_agentic_step": "confirm",
    "diagnose_run_on_failure": "review",
    "defect_close_flake": false,
    "flaky_auto_rerun": "suggest",
    "...": "..."
  },
  "tier": "CLOUD",
  "updated_at": "2026-05-26T12:00:00Z",
  "updated_by": "user_42"
}
```

`effective` is server-computed from `level + overrides`, given for the UI's convenience.

### PUT request

```json
{
  "level": "semi_auto",
  "overrides": { "defect_close_flaky": false, "auto_pr_fix": true }
}
```

### Validation

- Tier=ZERO: only `level=manual` is accepted; any other returns `400 AUTONOMY_REQUIRES_LLM`.
- Unknown override keys: `400 UNKNOWN_OVERRIDE_KEY`.
- Override that requires a feature flag (`auto_pr_fix` needs `gh_app_installed=true`): `400 OVERRIDE_REQUIRES_INTEGRATION`.

### Audit

Every `PUT` writes a row to `audit_logs` with the diff captured inside `metadata` (see § 12 for the canonical schema):

```python
audit_logs.insert(
    workspace_id=ws_id,
    user_id=user_id,
    action="autonomy.update",
    resource_type="workspace",
    resource_id=ws_id,
    metadata={
        "actor_type": "user",
        "before": {"level": "assist", "overrides": {}},
        "after":  {"level": "semi_auto", "overrides": {"defect_close_flaky": False}},
        "reason": request.json.get("reason"),  # optional, recommended for compliance
    },
)
```

---

## 7. UI surface

**Settings → Automation** tab. Single page.

1. **Radio group** (4 cards, one per level). Selected card highlighted with `accent` border.
2. Each card shows:
   - Level name + 1-line description
   - "In this level, the agent will:" preview — generated from the matrix in § 3
   - "Recommended for:" hint (`assist` → "Most teams", `auto` → "Production CI pipelines")
3. **Collapsible** "Advanced overrides" panel under the radio group, lists every override key as a toggle. Disabled toggles show a tooltip explaining why (e.g. "Requires GitHub App installation").
4. **Save** button → `PUT /workspaces/:id/autonomy`, optimistic update, toast on success.
5. **Preview banner** above the form: live-recomputed `effective` summary as user toggles.

```
Settings → Automation
─────────────────────
( ) manual       (•) assist        ( ) semi_auto    ( ) auto
    Human-only      AI suggests        P2/P3 auto       Hands-off CI
    workflow.       human approves.    P0/P1 gated.     mode.

▾ Advanced overrides (3 of 10 enabled)
  [✓] gen_finalize_p2p3
  [ ] defect_close_flaky        (level default: ON in semi_auto+)
  [✓] flaky_auto_rerun
  ...

Effective behavior preview:
  • Generation:   AI proposes, status=DRAFT
  • Execution:    confirm each agentic step
  • Diagnosis:    AI runs, human reviews before close
  ...

                              [ Save changes ]
```

---

## 8. Upgrade prompts

### 8.1 First LLM key added in ZERO workspace

Modal blocks rest of UI until dismissed:

```
┌──────────────────────────────────────────────────┐
│ AI is now available                              │
├──────────────────────────────────────────────────┤
│ Your workspace just gained LLM features.         │
│ How autonomous should the agent be?              │
│                                                  │
│  (•) Assist (recommended)                        │
│      AI suggests; you approve every action.      │
│                                                  │
│  ( ) Semi-auto                                   │
│      Low-priority items run automatically.       │
│      You stay in the loop for P0/P1.             │
│                                                  │
│  ( ) Manual                                      │
│      Keep things how they were. AI off.          │
│                                                  │
│      [ Decide later ]      [ Confirm ]           │
└──────────────────────────────────────────────────┘
```

`Decide later` → workspace stays at `manual` until admin opts in. No nag.

### 8.2 Switching from `assist` → `auto`

Requires typed confirmation:

```
┌──────────────────────────────────────────────────┐
│ Switch to Auto autonomy?                         │
├──────────────────────────────────────────────────┤
│ In Auto mode, the agent will:                    │
│   • finalize all generated test cases            │
│   • execute agentic steps without prompts        │
│   • file defects automatically                   │
│   • mark FLAKEs resolved after N green retries   │
│                                                  │
│ Safety rails still apply — see docs.             │
│                                                  │
│ Type "I understand AI will act without my        │
│ approval." to continue:                          │
│                                                  │
│   [ ___________________________________________] │
│                                                  │
│      [ Cancel ]            [ Switch to Auto ]    │
└──────────────────────────────────────────────────┘
```

Typed string must match exactly. Server-side recheck on PUT.

### 8.3 Downgrades

Any level → any lower level: no typed confirm, single-click. Always allowed. Audited.

---

## 9. Safety rails (always enforced)

Hardcoded in code paths regardless of level + override. Override flags **cannot** turn these off.

| Rail | Enforced at | Behavior |
|------|-------------|----------|
| **No autonomous delete** | `cases.delete`, `suites.delete`, `defects.delete` | Agent role rejected (`403 RAIL_NO_DELETE`). Human-only. |
| **No autonomous defect close** | `PATCH /defects/:id` with `status=CLOSED` | Agent may set `RESOLVED`; only human can `CLOSED`. |
| **No push to main** | GitHub App permissions | Agent can open PRs targeting non-default branches only. |
| **Spend cap respected** | `enforce_budget()` in LiteLLM router ([AI_AGENT.md § 14](./AI_AGENT.md)) | Hard cap returns 429 even in `auto`. |
| **Audit log for every autonomous action** | `audit_logs` row with `user_id=NULL` + `metadata.actor_type='agent'`, `metadata.autonomy_level_at_time`, `metadata.reason`, `metadata.correlation_id` (agent session id) — see § 12 | Append-only, non-deletable. |
| **PII / secret scrubbing** | All prompt + tool-call logs run through scrubber before persist | Regex + entropy heuristics. |
| **Conversation mutation confirm** | `tasks/conversation.py` | Mutations from chat always require UI confirm even in `auto`. |
| **Production target lock** | Workspace setting `is_production=true` adds an extra gate to destructive ops regardless of autonomy | E.g. `DELETE` ops in DB MCP plugin require typed env name in request body. |

> **Tip**: a useful pattern is workspace_per_env (dev workspace = `auto`, prod workspace = `assist`). Tier and autonomy are per workspace, so this composes naturally.

---

## 10. Default per tier

| Tier | Default autonomy | Forced? | Notes |
|------|------------------|:-------:|-------|
| ZERO | `manual` | yes | Only valid value. AI UI hidden. |
| LOCAL | `assist` | no | User may downgrade to `manual` or upgrade to `semi_auto` / `auto`. |
| CLOUD | `assist` | no | Same as LOCAL. Some shops keep CLOUD at `manual` (LLM configured but only used for one-off chat). |

Tier downgrade resets autonomy: dropping CLOUD → ZERO (e.g. unsetting `SUITEST_LLM_PROVIDER`) forces autonomy back to `manual` at next process start, with an audit entry `actor='system'`, `reason='tier_downgrade'`.

---

## 11. Programmatic control

### Python SDK

```python
from suitest_sdk import SuitestClient
client = SuitestClient(base_url="https://suitest.acme.dev", token=TOKEN)

client.workspaces.set_autonomy(
    workspace_id="ws_42",
    level="semi_auto",
    overrides={"defect_close_flaky": False},
)
```

### CLI

```bash
suitest workspace autonomy set --level semi_auto \
        --override defect_close_flaky=false
suitest workspace autonomy get
```

### CI per-run override

A CI job can override autonomy **downward** for a single run via env var, only if the workspace setting permits:

```bash
# In CI YAML
env:
  SUITEST_AUTONOMY: assist        # downgrade for this run only
```

Validation:

- `SUITEST_AUTONOMY` value must be `≤ workspace.level` (downgrades only; cannot grant powers not configured).
- Workspace setting `allow_run_autonomy_override = true|false` (default `true`).
- Override applies only to the API/run started with that env; persisted nothing.

### REST

```http
POST /runs
Content-Type: application/json
X-Suitest-Autonomy: assist        # optional per-run downgrade
```

Server: `effective = min(workspace.level, header.value if allowed else workspace.level)`.

---

## 12. Audit & compliance

Every autonomous action writes to the canonical `audit_logs` table (see [DATA_MODEL.md §3.11](./DATA_MODEL.md)). The autonomy-specific context (`actor_type`, `autonomy_level_at_time`, `overrides_at_time`, `before`, `after`, `correlation_id`, `reason`) is emitted **inside the `audit_logs.metadata` JSONB column** — it is **not** a separate table or extra top-level columns.

### 12.1 Canonical schema (read-only summary)

```python
# packages/db/src/suitest_db/models/audit_log.py — canonical
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    user_id: Mapped[UUID | None]       # NULL when actor is agent or system
    action: Mapped[str]                # e.g. "case.create", "defect.file", "autonomy.update"
    resource_type: Mapped[str]         # "test_case", "defect", "workspace", ...
    resource_id: Mapped[UUID | None]
    metadata: Mapped[dict]             # JSONB — autonomy + diff context lives here
    created_at: Mapped[datetime]
```

### 12.2 Field mapping (legacy → canonical)

| Legacy column (this doc, pre-fix) | Canonical location |
|-----------------------------------|--------------------|
| `actor_type` (`user` / `agent` / `system`) | Derived: `metadata.actor_type` (and `user_id IS NULL` ⇒ non-user actor) |
| `actor_id` | `user_id` when human; otherwise `metadata.actor_id` (e.g. agent session id) |
| `target_type` | `resource_type` |
| `target_id` | `resource_id` |
| `autonomy_level_at_time` | `metadata.autonomy_level_at_time` |
| `overrides_at_time` | `metadata.overrides_at_time` |
| `before` | `metadata.before` |
| `after` | `metadata.after` |
| `correlation_id` | `metadata.correlation_id` (typically the `agent_session_id`) |
| `reason` | `metadata.reason` |

### 12.3 Example payload

A `PUT /workspaces/:id/autonomy` from § 6 writes the following row:

```json
{
  "id": "01J9ABCD...",
  "workspace_id": "ws_42",
  "user_id": "user_17",
  "action": "autonomy.update",
  "resource_type": "workspace",
  "resource_id": "ws_42",
  "metadata": {
    "actor_type": "user",
    "actor_id": "user_17",
    "autonomy_level_at_time": "assist",
    "overrides_at_time": {},
    "before": { "level": "assist", "overrides": {} },
    "after":  { "level": "semi_auto", "overrides": { "defect_close_flaky": false } },
    "correlation_id": null,
    "reason": "CI rollout to staging"
  },
  "created_at": "2026-05-30T09:15:42Z"
}
```

An autonomous agent action (e.g. agent files a defect under `semi_auto`):

```json
{
  "workspace_id": "ws_42",
  "user_id": null,
  "action": "defect.file",
  "resource_type": "defect",
  "resource_id": "dfk_7831",
  "metadata": {
    "actor_type": "agent",
    "actor_id": "sess_a1b2c3",
    "autonomy_level_at_time": "semi_auto",
    "overrides_at_time": { "defect_close_flaky": false },
    "before": null,
    "after": { "status": "OPEN", "severity": "P2", "category": "FLAKE" },
    "correlation_id": "sess_a1b2c3",
    "reason": "Step 4 failed: assertion mismatch on /orders contract"
  }
}
```

- **Append-only**. No `DELETE` privilege on `audit_logs` table to any application role.
- **Retention**: default 13 months, configurable per workspace.
- **Export**: `GET /workspaces/:id/audit?from=&to=&format=csv|jsonl` for SOC2 / ISO27001 evidence collection.
- **Search**: indexed by `(workspace_id, created_at)`, `(action)`, `(resource_type, resource_id)`; JSONB GIN index on `metadata` for filters such as `metadata->>'actor_type' = 'agent'`.

Compliance defaults shipped:

| Standard | What this covers |
|----------|------------------|
| **SOC 2 CC6.1, CC6.6** | Logical access — actor + action + before/after |
| **SOC 2 CC7.2** | Change monitoring — autonomy changes audited (§ 6) |
| **ISO 27001 A.12.4** | Logging + monitoring — append-only audit log |
| **EU AI Act art. 12** | Automatic logging — every autonomous decision recorded |

> **Note**: Audit log is the source of truth for "did the agent close this defect or did a human?". UIs that render defect history MUST show the `actor_type` badge.
