---
title: Data model
description: Workspaces, projects, suites, test cases, runs, defects, requirements, and artifacts, how they relate, and where each shows up in the dashboard.
---

Everything Suitest produces lives in a small, predictable hierarchy. This page walks through the entities, how they relate, and where each one shows up in the web dashboard.

## The hierarchy

```text
Workspace
 |-- Members (roles: OWNER, ADMIN, QA, VIEWER)
 |-- Projects
 |    |-- Suites
 |    |    +-- Test cases
 |    |         +-- Steps (action, expected, code, mcp_provider, target_kind)
 |    |-- Runs
 |    |    +-- Run steps
 |    |         +-- Artifacts (screenshot, video, HAR, DOM snapshot, ...)
 |    +-- Requirements <-> Test cases (traceability links)
 |-- Defects (link to a test case, run, and requirement)
 |    +-- External issues (Jira, Linear, GitHub)
 |-- MCP providers (registry)
 |-- LLM config (drives the capability tier)
 |-- Integrations
 +-- Audit log
```

Everything is workspace scoped. API requests resolve through your workspace membership, and objects from another workspace are simply not found.

## Workspaces and members

A **workspace** is the tenancy boundary: your team, your data, your configuration. It owns:

- **Members** with a role: `OWNER`, `ADMIN`, `QA`, or `VIEWER`. Onboarding is invite based.
- **LLM configuration**, set in Settings, which determines the workspace's [capability tier](/docs/reference/tiers/).
- **MCP routing overrides**: a per workspace map from `target_kind` to a preferred MCP provider.
- The `strict_zero_validation` setting, which controls whether steps without executable code can be saved when no LLM is configured.

## Projects and suites

A **project** groups the testing effort for one application. Projects own suites, runs, and requirements. A project can pin a **gating suite**: the suite that webhook triggered CI runs execute against.

A **suite** is a logical grouping of test cases (smoke, regression, checkout flow). Suites carry a manual ordering, can define their own MCP routing overrides (suite overrides win over workspace overrides), and are soft deleted so they can be restored.

## Test cases and steps

A **test case** is the central managed artifact: a documented, owned, executable test. Its key fields:

| Field | Meaning |
|-------|---------|
| `public_id` | Stable human readable identifier shown in the UI |
| `title` | Human readable display title, the only field the UI renders as a heading |
| `slug` | Technical key: the generated test function name, used to match published automation to the case |
| `name` | Legacy compatibility field, also the publish idempotency fallback |
| `source` | Where the case came from: `MANUAL`, `AI`, `MCP`, `IMPORT`, `RECORDER`, `HEURISTIC_CRAWL` |
| `status` | `DRAFT`, `ACTIVE`, `STALE`, `DEPRECATED`, `ARCHIVED` |
| `priority` | `P0` through `P3` |
| `preconditions` | Setup the test assumes |
| `automation_code` | The full generated test source, rendered in the case's Code tab |
| `last_run_*` | Denormalized result of the most recent run: result, time, failure reason, duration |

Cases also carry free form **tags** and an owner.

Each case contains ordered **steps**. A step is one action with one expectation:

- `action`: what to do, in plain language ("Click the login button").
- `expected`: the expected result, which is what assertions verify.
- `code`: optional executable code for the step. When present, the runner executes it deterministically.
- `data`: optional structured input for the step.
- `mcp_provider` and `target_kind`: which MCP provider executes this step and what kind of target it touches (`FE_WEB`, `BE_REST`, `DATA`, and so on).

Whether a step is *executable* is computed, not stored: a step with `code` is always executable; a step with only an `action` is executable only when the workspace has an LLM tier that can translate it at runtime. See [Capability tiers](/docs/reference/tiers/).

:::note
Because routing is per step, a single test case can mix providers: seed the database through the Postgres provider, call an endpoint through the HTTP provider, then verify the UI through the Playwright provider, all in one run.
:::

## Runs and run steps

A **run** is one execution of one or more test cases. Runs belong to a project and record the execution context:

- `public_id` (for example `R-1004`), which the web UI routes on.
- `branch`, `commit_sha`, and `env` (staging, production, and so on).
- `trigger`: `MANUAL`, `SCHEDULED`, `CI_PUSH`, `CI_PR`, `WEBHOOK`, or `AGENT`.
- `status`: `QUEUED`, `RUNNING`, `PASS`, `FAIL`, `CANCELLED`, or `ERROR`.
- `tier_at_runtime`: the capability tier captured when the run started, so historical runs stay reproducible even after you change your LLM configuration.
- Step counters: total, passed, failed.

Each run fans out into **run steps**, one row per executed test step, each with:

- an `outcome`: `PASS`, `FAIL`, `SKIP`, `ERROR`, or `PENDING`
- timing (`started_at`, `completed_at`, `duration_ms`)
- captured `stdout` and `stderr`
- `error_message` and `error_stack` on failure
- a state snapshot of the normalized MCP output, which powers the run replay view

Runs are created through the API (`POST /api/v1/runs`, or `POST /api/v1/suites/{suite_id}/run` to run a whole suite), queued to the runner, and can be cancelled while queued or running, or rerun with the identical selection.

## Artifacts

An **artifact** is a file produced during execution, attached to the run step that produced it. Kinds: `SCREENSHOT`, `VIDEO`, `HAR`, `DOM_SNAPSHOT`, `CONSOLE_LOG`, `TRACE`, and `CUSTOM`. Each row records the storage URL, size, and MIME type.

Artifacts are the proof layer of Suitest and have their own page: [Evidence](/docs/concepts/evidence/).

## Defects

A **defect** is a bug record, usually created from a failing run. Defects live at the workspace level and can link to the test case that caught the bug, the run that exposed it, and the requirement it violates.

| Field | Values |
|-------|--------|
| `severity` | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` |
| `status` | `OPEN`, `IN_PROGRESS`, `RESOLVED`, `CLOSED`, `WONT_FIX` |
| `agent_diagnosis_kind` | `REGRESSION`, `FLAKE`, `INFRA`, `SPEC_DRIFT`, or `MANUAL_TRIAGE` |

Without an LLM, failed runs file rule based defects tagged for manual triage. With an LLM configured, diagnosis can classify the failure and attach a root cause narrative with a confidence score.

Defects can be mirrored to your issue tracker: an **external issue** row records the Jira, Linear, or GitHub counterpart and keeps the link stable across syncs.

## Requirements and traceability

A **requirement** represents something the application must do, with a title, description, and an optional link to its source (a PRD section, a ticket URL). Requirements belong to a project.

Traceability is a link table between requirements and test cases: one requirement can be covered by many cases, and one case can cover many requirements. Defects can also reference a requirement. Together this closes the loop the dashboard renders as the **traceability matrix**: requirement, the cases that cover it, their latest results, and any open defects.

## What the dashboard shows

Each dashboard area maps directly onto these entities:

| Screen | Backed by |
|--------|-----------|
| Dashboard | Aggregates over runs and defects: pass rate, readiness |
| Projects, Suites, Cases | Projects, suites, test cases; the case detail has tabs for steps, evidence, and generated code |
| Runs | Runs and run steps, with live status over WebSocket, logs, video, and a summary bar (active, today, passed, failed) |
| Defects | Defects and their external issues |
| Traceability | Requirements and requirement to case links |
| Integrations | Integration records (GitHub, GitLab, Jira, Slack) and the MCP provider registry |
| Settings | Workspace, members, LLM configuration, autonomy, API keys |

The REST API mirrors the same shape: routers exist per entity (projects, suites, test cases, runs, defects, requirements, analytics, MCP providers, LLM config, and more). See the [API reference](/docs/reference/api/).

## Identifiers

Every user facing entity has two identifiers:

- an internal primary key, used in API paths and foreign keys
- a `public_id`, the short stable identifier shown in the UI (runs look like `R-1004`)

Run endpoints accept either form, so links copied from the dashboard resolve directly against the API.

## Next steps

- [Evidence](/docs/concepts/evidence/): what artifacts contain and how to fetch them
- [How Suitest works](/docs/concepts/how-it-works/): the pipeline that populates all of this
- [Capability tiers](/docs/reference/tiers/): how the tier changes step validation and execution
