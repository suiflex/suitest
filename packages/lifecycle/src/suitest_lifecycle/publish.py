"""Publish lifecycle results into a running Suitest (Approach A — REST ingest).

Builds the bulk-import (cases + steps + source code) and run-ingest (completed
run + per-step outcomes + video/screenshot artifacts) payloads, then sends them
via the Suitest SDK. The SDK is imported lazily so the lifecycle core stays
stdlib-only; if it (or the server) is unavailable, publishing degrades to a
clean ``{"published": False, "reason": ...}`` instead of failing the run.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from suitest_lifecycle.config import Config
    from suitest_lifecycle.models import PlanCase, RunSummary
    from suitest_lifecycle.paths import Paths


class Uploader(Protocol):
    """Minimal upload surface the publisher needs (satisfied by SuitestClient).

    Artifacts go THROUGH the API — the server holds the S3 credentials, so the
    lifecycle/MCP client needs no ``SUITEST_S3_*`` env of its own.
    """

    def upload_file(self, path: str, *, content_type: str | None = None) -> str: ...


_PRIORITY = {"High": "P1", "Medium": "P2", "Low": "P3"}
_MIME = {".webm": "video/webm", ".png": "image/png", ".jpg": "image/jpeg"}

# PlanCase.title is the generated test function slug (codegen emits
# ``test_<title>``), so the publish layer is where the human display title is
# minted: ``slug`` carries the technical key, ``title`` the readable sentence.
# Mirrors suitest_shared.text.humanize_slug (lifecycle stays stdlib-only).
_ACRONYMS = frozenset({"api", "url", "id", "ui", "ux", "http", "sql", "ok", "sso", "mcp"})


def _humanize(slug: str) -> str:
    words = [w for w in slug.replace("_", " ").replace("-", " ").split() if w]
    if not words:
        return slug.strip()
    out: list[str] = []
    for i, word in enumerate(words):
        lower = word.lower()
        if lower in _ACRONYMS:
            out.append(lower.upper())
        elif i == 0:
            out.append(word[:1].upper() + word[1:].lower())
        else:
            out.append(lower)
    return " ".join(out)


def _suite_name(config: Config) -> str:
    return config.publish.suite_name or f"{config.project_name} {config.mode.value}"


def _case_payloads(cases: list[PlanCase], paths: Paths) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for c in cases:
        code = ""
        if c.automation_file:
            fp = paths.test_file(c.automation_file)
            if fp.is_file():
                code = fp.read_text(encoding="utf-8")
        out.append(
            {
                "sourceRef": c.source_ref,
                # ``name`` stays the slug — it is the server's idempotency match
                # key for rows published before the title/slug split.
                "name": c.title,
                "slug": c.title,
                "title": _humanize(c.title),
                "description": c.description,
                # Lifecycle cases are produced by the MCP-native plan/run loop, so
                # they surface under the MCP filter (not the generic IMPORT bucket).
                "source": "MCP",
                "priority": _PRIORITY.get(c.priority.value, "P2"),
                "category": c.category,
                "tags": list(c.tags),
                "automationFilePath": c.automation_file,
                "automationCode": code,
                "generatedBy": "suitest-lifecycle",
                "steps": [
                    {
                        "order": i + 1,
                        "action": s.description,
                        # For assertions the description *is* the expectation; for
                        # actions there's no distinct expected, so leave it blank
                        # and let the reader derive one.
                        "expected": s.description if s.type == "assertion" else "",
                        "code": None,
                    }
                    for i, s in enumerate(c.steps)
                ],
            }
        )
    return out


def _resolve_url(client: Uploader, path: str, mime: str) -> str:
    """Upload the artifact THROUGH the API (server owns the S3 creds) and return
    the durable ``s3://`` URL. On any upload hiccup fall back to a local
    ``file://`` URL so publishing never fails on an artifact."""
    try:
        return client.upload_file(path, content_type=mime)
    except Exception:  # never fail publish on an upload hiccup
        return "file://" + os.path.abspath(path)


def _artifact(client: Uploader, path: str, kind: str) -> dict[str, object] | None:
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    mime = _MIME.get(ext, "application/octet-stream")
    return {
        "kind": kind,
        "url": _resolve_url(client, path, mime),
        "mimeType": mime,
        "sizeBytes": os.path.getsize(path),
    }


def _result_payloads(
    client: Uploader, summary: RunSummary, cases: list[PlanCase]
) -> list[dict[str, object]]:
    ref_by_id = {c.id: c.source_ref for c in cases}
    name_by_id = {c.id: c.title for c in cases}
    out: list[dict[str, object]] = []
    for r in summary.results:
        # Case level carries only the VIDEO now; screenshots are per-step (each
        # run_step gets its own SCREENSHOT), so the "final" one would be redundant.
        artifacts = [a for a in (_artifact(client, r.video_path, "VIDEO"),) if a is not None]
        slug = name_by_id.get(r.test_id, r.title)
        out.append(
            {
                "name": slug,
                "slug": slug,
                "sourceRef": ref_by_id.get(r.test_id, r.test_id),
                "outcome": r.status.value,
                "durationMs": r.duration_ms,
                "error": r.error,
                "steps": [
                    {
                        "order": s.index,
                        "type": s.type,
                        "description": s.description,
                        "outcome": s.status.value,
                        # Per-step screenshot, uploaded so the web can sign + show it.
                        "screenshot": (
                            _resolve_url(client, s.screenshot_path, "image/png")
                            if s.screenshot_path and os.path.isfile(s.screenshot_path)
                            else ""
                        ),
                    }
                    for s in r.steps
                ],
                "artifacts": artifacts,
            }
        )
    return out


def publish_results(
    config: Config, summary: RunSummary, cases: list[PlanCase], paths: Paths
) -> dict[str, object]:
    if not config.publish.enabled:
        return {"published": False, "reason": "publish disabled"}
    if not config.publish.project_id:
        return {"published": False, "reason": "publish.projectId not set"}
    try:
        from suitest_sdk import SuitestAPIError, SuitestClient
    except ImportError:
        return {"published": False, "reason": "suitest-sdk not installed"}

    suite = _suite_name(config)
    # Secrets (the API key) and the endpoint can come from the environment so
    # they stay out of a committed suitest.config.json — the MCP client injects
    # SUITEST_API_KEY / SUITEST_API_URL. Config values win when both are set.
    api_url = config.publish.api_url or os.environ.get("SUITEST_API_URL", "")
    token = config.publish.token or os.environ.get("SUITEST_API_KEY") or None
    client = SuitestClient(
        api_url,
        token=token,
        workspace_id=config.publish.workspace_id or None,
        # Video artifacts upload THROUGH the API to remote object storage — the
        # default 30s regularly times out on multi-MB webm files.
        timeout=180.0,
    )
    try:
        with client:
            imported = client.bulk_import_cases(
                project_id=config.publish.project_id,
                suite_name=suite,
                mode=config.mode.value,
                cases=_case_payloads(cases, paths),
            )
            run = client.ingest_run(
                project_id=config.publish.project_id,
                suite_name=suite,
                name=f"{config.project_name} lifecycle",
                results=_result_payloads(client, summary, cases),
            )
    except SuitestAPIError as exc:
        return {"published": False, "reason": f"api error: {exc}"}
    except Exception as exc:  # publish must never fail the run (network/SDK errors)
        return {"published": False, "reason": f"connection error: {type(exc).__name__}: {exc}"}
    return {
        "published": True,
        "runId": run.get("runId") if isinstance(run, dict) else None,
        "imported": len(imported.get("imported", [])) if isinstance(imported, dict) else 0,
    }


__all__ = ["publish_results"]
