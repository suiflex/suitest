---
title: Evidence
description: What Suitest records for every run and step, where artifacts are stored, how downloads work, and how evidence feeds the agent fix loop.
---

Suitest captures proof, not just verdicts. Every run step can leave behind files that show exactly what happened: what the page looked like, what the browser logged, which requests failed. This page covers what gets recorded, where it lives, and how it turns a red run into something an agent can act on.

## What gets recorded

Artifacts are typed. Each one attaches to the specific run step that produced it:

| Kind | What it is |
|------|-----------|
| `SCREENSHOT` | Page screenshot, captured per step or per test |
| `VIDEO` | Per test video of the browser session |
| `DOM_SNAPSHOT` | The page DOM as captured during analysis or at failure |
| `CONSOLE_LOG` | Browser console output |
| `HAR` | Network capture in HTTP Archive format |
| `TRACE` | Execution trace |
| `CUSTOM` | Anything else a provider emits |

Alongside artifacts, every run step also persists its `stdout`, `stderr`, `error_message`, and `error_stack` directly in the database, and a normalized state snapshot of the MCP output that powers the run replay view.

:::note
Evidence recording is a toggle. Video, for example, is recorded when you enable it (`--record-video` on the blackbox CLI, or the evidence recording flag). The DOM, console, and network context used by the failure bundle also comes from this recording path.
:::

## How capture works

Test steps execute through MCP providers (Playwright for the browser, HTTP for APIs, Postgres for data checks). A provider can emit artifacts as part of a tool call. After each step, the runner:

1. Builds a deterministic storage key that mirrors the run and step tree:

   ```text
   runs/<run_id>/step-<step_order>/<kind>/<filename>
   ```

2. Writes the bytes through the configured storage backend.
3. Inserts one row in the `artifacts` table linking the file back to its run step, with the canonical URL, size in bytes, and MIME type.

Because the key embeds the step order and artifact kind, artifacts sort naturally under their run prefix and identical filenames from different kinds never collide.

MIME types are resolved in order: the type the producing provider declared, then a guess from the filename suffix, then `application/octet-stream` as the final fallback.

### The artifact record

Each uploaded file gets one row in the database, which is what the list endpoint returns:

| Field | Meaning |
|-------|---------|
| `id` | Artifact identifier, used in the download endpoint |
| `run_step_id` | The run step this artifact belongs to |
| `kind` | One of the kinds above (`SCREENSHOT`, `VIDEO`, ...) |
| `url` | Canonical storage URL (`s3://bucket/key` or `local://key`) |
| `size_bytes` | Object size |
| `mime_type` | Resolved content type |
| `metadata` | Optional provider supplied context |

## Where artifacts are stored

Two storage backends exist, selected by the runner configuration:

| Mode | Backend | Artifact URL |
|------|---------|--------------|
| Server (default) | S3 compatible object store (MinIO in the standard deployment, or any S3 endpoint) | `s3://<bucket>/<key>` |
| Local | A plain folder on disk | `local://<key>` |

The default Docker deployment ships MinIO, so nothing leaves your infrastructure. See [Self hosting](/docs/guides/self-hosting/) and the [environment reference](/docs/reference/environment/) for the S3 settings.

## Downloading artifacts

The API never streams object store bytes through itself for S3 artifacts. Instead it hands you a short lived presigned URL:

```text
GET /api/v1/runs/{run_id}/artifacts                 # list a run's artifacts
GET /api/v1/runs/{run_id}/artifacts/{artifact_id}   # get a download URL for one
```

The second endpoint returns the artifact's kind and MIME type plus a URL:

- For `s3://` artifacts: a presigned S3/MinIO download URL valid for one hour (`expires_in_seconds: 3600`). Your client fetches directly from object storage.
- For `local://` artifacts: a pointer to `GET /api/v1/runs/{run_id}/artifacts/{artifact_id}/raw`, which streams the file from disk through the API, still gated by workspace membership.

Every signed URL request writes an audit log entry, so download attribution is captured even though the actual fetch happens against S3.

:::caution
Presigned URLs expire after one hour. Do not persist them; store the artifact id and request a fresh URL when you need the file again.
:::

## Logs, replay, and reports

Evidence is more than files:

- **Run logs.** `GET /api/v1/runs/{run_id}/logs` returns the persisted log stream (each step's stdout and stderr in step order) with cursor pagination. While a run is live, the same lines stream over WebSocket to the run detail page.
- **Replay.** `GET /api/v1/runs/{run_id}/replay` returns the ordered steps with each step's captured state snapshot and a computed delta against the previous step, a time travel view of what changed when.
- **JUnit export.** `GET /api/v1/runs/{run_id}/report.junit` renders the run as JUnit XML for CI test reporters.

On the telemetry side, every MCP tool invocation emits an OpenTelemetry span (provider, tool, duration, outcome), exportable to your OTLP backend. That gives you tracing across the runner and providers in the observability stack you already run.

## Evidence in the dashboard

The run detail page is built on this data: live step outcomes, the log stream, recorded video, and per step artifacts. On the test case side, the case detail's evidence tab shows the recordings attached to that case's runs, next to the generated code tab. See [Data model](/docs/concepts/data-model/) for how cases, runs, and artifacts relate.

## How evidence powers the agent fix loop

The reason Suitest records this much is not archival. It is so a coding agent can fix the failure without asking you to reproduce it.

When a run fails, the failure context serializer condenses the evidence into a compact, agent readable bundle. It is deliberately a set of smart excerpts, not a dump:

- **Console:** error and warning lines only, keeping the last entries closest to the failure.
- **Network:** failed requests only (non 2xx/3xx), each with method, URL, status, and a short response body snippet.
- **DOM:** not the whole page, just the subtree around the selector that failed, with a few lines of context and similar candidate elements.
- **Error:** the failing step, its description, and the actual error message extracted from the stack.
- **Evidence links:** pointers to the screenshot and video for the failing test.

The whole bundle is byte budgeted (8 KB by default, enforced on the encoded bytes), so it fits in an agent's context window alongside your actual code. The agent reads it, edits the application, and reruns until green.

See [Failure context](/docs/guides/failure-context/) for the format in detail and [Agent workflow](/docs/guides/agent-workflow/) for the loop end to end.

:::tip
The bundle only includes what exists. A missing video or an absent DOM capture drops that section rather than failing the whole bundle, so a partial bundle still beats no bundle.
:::

## Next steps

- [Failure context](/docs/guides/failure-context/): the agent readable failure bundle
- [Data model](/docs/concepts/data-model/): runs, run steps, and artifacts in context
- [Self hosting](/docs/guides/self-hosting/): configuring MinIO or S3
