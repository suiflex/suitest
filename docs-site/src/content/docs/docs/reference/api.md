---
title: REST API reference
description: Overview of the Suitest REST API under /api/v1, authentication with API keys, and a grouped tour of the main endpoints.
---

The Suitest API is a FastAPI application. All REST endpoints live under the `/api/v1` prefix (two exceptions: the capabilities probe and the WebSocket gateway, both at the root). A running instance serves its own always-current contract:

- Interactive docs (Swagger UI): `/docs`
- OpenAPI 3 schema: `GET /openapi.json`

The official [Python SDK](https://github.com/suiflex/suitest/tree/main/sdk/python) and [TypeScript SDK](https://github.com/suiflex/suitest/tree/main/sdk/typescript) track this schema.

## Authentication

- **Bearer token.** Send `Authorization: Bearer <token>`. Interactive users get a session from the login flow; programmatic clients use API keys.
- **API keys.** Created per workspace: `POST /api/v1/workspaces/{workspaceId}/api-keys`. Verify a key and see what it is bound to with `GET /api/v1/api-keys/whoami` (this is also what the MCP server calls at startup).
- **Workspace scoping.** Scope requests with the `X-Workspace-Id` header (the CLI's `--workspace` flag sets it).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/api-keys/whoami` | Identify the calling API key (workspace/project binding) |
| GET | `/api/v1/workspaces/{workspaceId}/api-keys` | List a workspace's API keys |
| POST | `/api/v1/workspaces/{workspaceId}/api-keys` | Create an API key |
| DELETE | `/api/v1/workspaces/{workspaceId}/api-keys/{keyId}` | Revoke an API key |

## Projects and suites

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/projects` | List projects (paginated) |
| GET | `/api/v1/projects/{project_id}` | Project detail |
| POST | `/api/v1/projects` | Create a project |
| PATCH | `/api/v1/projects/{project_id}` | Update a project |
| DELETE | `/api/v1/projects/{project_id}` | Soft-delete a project |
| POST | `/api/v1/projects/{project_id}/restore` | Restore a deleted project |
| GET | `/api/v1/suites` | List suites |
| GET | `/api/v1/suites/{suite_id}` | Suite detail |
| POST | `/api/v1/suites` | Create a suite |
| PATCH | `/api/v1/suites/{suite_id}` | Update a suite |
| DELETE | `/api/v1/suites/{suite_id}` | Soft-delete a suite |
| POST | `/api/v1/suites/{suite_id}/restore` | Restore a deleted suite |

## Test cases

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/test-cases` | List cases (paginated, filterable) |
| GET | `/api/v1/test-cases/search` | Search cases (semantic when embeddings are configured, lexical otherwise) |
| GET | `/api/v1/test-cases/{case_id}` | Case detail |
| GET | `/api/v1/test-cases/{case_id}/steps` | List a case's steps |
| POST | `/api/v1/test-cases` | Create a case |
| PATCH | `/api/v1/test-cases/{case_id}` | Update a case |
| PATCH | `/api/v1/test-cases/{case_id}/steps` | Replace a case's steps |
| POST | `/api/v1/test-cases/{case_id}/steps` | Add a step |
| PATCH | `/api/v1/test-cases/{case_id}/steps/reorder` | Reorder steps |
| POST | `/api/v1/test-cases/{case_id}/run` | Queue a run for one case |
| POST | `/api/v1/test-cases/{case_id}/duplicate` | Duplicate a case |
| DELETE | `/api/v1/test-cases/{case_id}` | Soft-delete a case |
| POST | `/api/v1/test-cases/bulk-update` | Bulk-update cases |
| POST | `/api/v1/test-cases/{case_id}/restore` | Restore a deleted case |
| GET | `/api/v1/test-cases/{case_id}/export` | Export a case |

## Runs, artifacts, and evidence

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/runs` | List runs (paginated) |
| GET | `/api/v1/runs/summary` | Aggregate run summary |
| GET | `/api/v1/runs/{run_id}` | Run detail |
| GET | `/api/v1/runs/{run_id}/steps` | Per-step results |
| GET | `/api/v1/runs/{run_id}/report.junit` | JUnit XML report |
| GET | `/api/v1/runs/{run_id}/replay` | Step-by-step replay payload |
| GET | `/api/v1/runs/{run_id}/logs` | Paged run logs |
| GET | `/api/v1/runs/{run_id}/artifacts` | List artifacts (screenshots, videos, HARs, logs) |
| GET | `/api/v1/runs/{run_id}/artifacts/{artifact_id}` | Presigned download URL for one artifact |
| GET | `/api/v1/runs/{run_id}/artifacts/{artifact_id}/raw` | Stream the artifact bytes through the API |
| GET | `/api/v1/runs/{run_id}/network` | Captured network activity |
| POST | `/api/v1/runs` | Queue a run for a case selection (202 Accepted) |
| POST | `/api/v1/suites/{suite_id}/run` | Queue a run for a whole suite (202 Accepted) |
| POST | `/api/v1/runs/{run_id}/cancel` | Cancel a run |
| POST | `/api/v1/runs/{run_id}/rerun` | Re-queue a finished run (202 Accepted) |

See [Evidence](/docs/concepts/evidence/) for where artifacts are stored and how they flow from the runner to object storage.

## Defects

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/defects` | List defects (paginated) |
| GET | `/api/v1/defects/{defect_id}` | Defect detail |
| GET | `/api/v1/defects/{defect_id}/timeline` | Defect timeline |
| POST | `/api/v1/defects` | Create a defect |
| PATCH | `/api/v1/defects/{defect_id}` | Update a defect |
| POST | `/api/v1/defects/{defect_id}/sync-external` | Sync with an external tracker (Jira/GitHub) |

## Requirements and traceability

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/requirements` | List requirements (paginated) |
| GET | `/api/v1/requirements/{requirement_id}` | Requirement detail |
| POST | `/api/v1/requirements` | Create a requirement |
| PATCH | `/api/v1/requirements/{requirement_id}` | Update a requirement |
| DELETE | `/api/v1/requirements/{requirement_id}` | Soft-delete a requirement |
| POST | `/api/v1/requirements/{requirement_id}/restore` | Restore a requirement |
| POST | `/api/v1/requirements/{requirement_id}/links` | Link a test case |
| DELETE | `/api/v1/requirements/{requirement_id}/links/{case_id}` | Unlink a test case |
| GET | `/api/v1/traceability/matrix` | Requirement/case/defect traceability matrix |

## Generators

Deterministic generators work at the ZERO tier; PRD and semantic generators need a workspace LLM.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/generators/classify` | Classify an input to pick a generator |
| POST | `/api/v1/generators/openapi` | Generate cases from an OpenAPI spec |
| POST | `/api/v1/generators/prd` | Generate cases from a PRD (LLM) |
| POST | `/api/v1/generators/url-semantic` | Generate cases from a URL semantically (LLM) |
| POST | `/api/v1/generators/mcp-discovery` | Generate cases from MCP provider discovery |
| POST | `/api/v1/generators/crawler` | Generate cases from a crawl |
| POST | `/api/v1/generators/recorder/sessions` | Start a browser recorder session |
| POST | `/api/v1/generators/recorder/sessions/{session_id}/finalize` | Finalize a recording into cases |
| DELETE | `/api/v1/generators/recorder/sessions/{session_id}` | Discard a recorder session |
| POST | `/api/v1/generators/diff-select` | Select cases affected by a diff |

## Ingest (used by the MCP server and CI)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/ingest/resolve-project` | Validate/repair a project binding before publishing |
| POST | `/api/v1/test-cases/bulk-import` | Bulk-import generated cases into a suite |
| POST | `/api/v1/runs/ingest` | Ingest an externally executed run with results and evidence |

## Capabilities, LLM config, and MCP providers

| Method | Path | Purpose |
|---|---|---|
| GET | `/capabilities` | Effective tier + feature flags (root path, no `/api/v1` prefix) |
| GET | `/capabilities/health` | Capability health probe |
| GET | `/api/v1/workspaces/{workspaceId}/llm-config` | Read the workspace LLM configuration |
| PUT | `/api/v1/workspaces/{workspaceId}/llm-config` | Set the workspace LLM provider |
| POST | `/api/v1/workspaces/{workspaceId}/llm-config/test` | Test the configured provider |
| DELETE | `/api/v1/workspaces/{workspaceId}/llm-config` | Remove the LLM configuration (back to ZERO) |
| GET | `/api/v1/workspaces/{workspaceId}/llm-config/models` | List available models for the provider |
| GET | `/api/v1/mcp/providers` | List MCP providers |
| GET | `/api/v1/mcp/providers/{provider_id}` | Provider detail |
| POST | `/api/v1/mcp/providers` | Register a provider |
| POST | `/api/v1/mcp/providers/test-connection` | Probe a provider config before saving |
| PATCH | `/api/v1/mcp/providers/{provider_id}` | Update a provider |
| DELETE | `/api/v1/mcp/providers/{provider_id}` | Remove a provider |
| POST | `/api/v1/mcp/providers/{provider_id}/discover` | Discover the provider's tools |
| POST | `/api/v1/mcp/providers/{provider_id}/invoke` | Invoke a provider tool |
| GET | `/api/v1/mcp/routing` | Read the target-kind routing table |
| PUT | `/api/v1/mcp/routing` | Update the routing table |

LLM providers are configured here (or in the web UI at Settings, LLM), never via environment variables. See [LLM setup](/docs/guides/llm-setup/).

## Integrations and inbound webhooks

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/integrations` | List integrations |
| GET | `/api/v1/integrations/{integration_id}` | Integration detail |
| POST | `/api/v1/integrations` | Create an integration |
| PATCH | `/api/v1/integrations/{integration_id}` | Update an integration |
| DELETE | `/api/v1/integrations/{integration_id}` | Remove an integration |
| POST | `/api/v1/integrations/{integration_id}/test` | Test an integration |
| POST | `/api/v1/integrations/{integration_id}/sync` | Trigger a sync |
| POST | `/api/v1/integrations/jira/test-connection` | Validate Jira credentials |
| POST | `/api/v1/integrations/github/test-connection` | Validate GitHub credentials |
| POST | `/api/v1/webhooks/github` | Inbound GitHub webhook |
| POST | `/api/v1/webhooks/gitlab` | Inbound GitLab webhook |
| POST | `/api/v1/webhooks/jira` | Inbound Jira webhook |

## Analytics

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/analytics/kpis` | Headline KPIs |
| GET | `/api/v1/analytics/pass-rate` | Pass-rate time series |
| GET | `/api/v1/analytics/coverage` | Coverage breakdown |
| GET | `/api/v1/analytics/flaky` | Flaky-case ranking |
| GET | `/api/v1/analytics/heatmap` | Activity heatmap |
| GET | `/api/v1/analytics/readiness` | Release readiness |

## Workspaces

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/workspaces` | List the caller's workspaces |
| POST | `/api/v1/workspaces` | Create a workspace |
| GET | `/api/v1/workspaces/{workspace_id}` | Workspace detail |
| PATCH | `/api/v1/workspaces/{workspace_id}` | Update a workspace |
| DELETE | `/api/v1/workspaces/{workspace_id}` | Delete a workspace |
| GET | `/api/v1/workspaces/{workspace_id}/members` | List members |
| POST | `/api/v1/workspaces/{workspace_id}/members` | Add a member |
| PATCH | `/api/v1/workspaces/{workspace_id}/members/{user_id}` | Change a member's role |
| DELETE | `/api/v1/workspaces/{workspace_id}/members/{user_id}` | Remove a member |
| POST | `/api/v1/workspaces/{workspace_id}/export` | Start a workspace export |
| GET | `/api/v1/workspaces/{workspace_id}/export/{job_id}` | Poll an export job |
| POST | `/api/v1/workspaces/import` | Import a workspace archive |

## WebSocket (live run logs)

| Method | Path | Purpose |
|---|---|---|
| WS | `/ws?token=<jwt>` | JWT-authenticated WebSocket for live run status and logs |

The gateway is mounted at the root (not under `/api/v1`). After connecting, clients send `subscribe` / `unsubscribe` / `ping` messages to follow runs in their workspaces. The web UI's live run view uses this channel.

## Other surfaces

The API also mounts routers for auth and user administration, invitations, files, documents, eval runs, audit logs, inbox notifications, autonomy, cost tracking, agent chat, the LLM proxy (`/llm/complete`, used by MCP codegen), prompts, and agent plugins. Explore them on a running instance at `/docs`.
