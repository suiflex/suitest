"""Publish lifecycle results into a running Suitest (Approach A — REST ingest).

Builds the bulk-import (cases + steps + source code) and run-ingest (completed
run + per-step outcomes + video/screenshot artifacts) payloads, then sends them
via the Suitest SDK. The SDK is imported lazily so the lifecycle core stays
stdlib-only; if it (or the server) is unavailable, publishing degrades to a
clean ``{"published": False, "reason": ...}`` instead of failing the run.
"""

from __future__ import annotations

import os

from suitest_lifecycle.config import Config
from suitest_lifecycle.models import PlanCase, RunSummary
from suitest_lifecycle.paths import Paths

_PRIORITY = {"High": "P1", "Medium": "P2", "Low": "P3"}
_MIME = {".webm": "video/webm", ".png": "image/png", ".jpg": "image/jpeg"}


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
                "name": c.title,
                "description": c.description,
                "priority": _PRIORITY.get(c.priority.value, "P2"),
                "category": c.category,
                "tags": list(c.tags),
                "automationFilePath": c.automation_file,
                "automationCode": code,
                "generatedBy": "suitest-lifecycle",
                "steps": [
                    {"order": i + 1, "action": s.description, "expected": s.description, "code": None}
                    if s.type == "action"
                    else {"order": i + 1, "action": s.description, "expected": s.description, "code": None}
                    for i, s in enumerate(c.steps)
                ],
            }
        )
    return out


def _artifact(path: str, kind: str) -> dict[str, object] | None:
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    return {
        "kind": kind,
        "url": "file://" + os.path.abspath(path),
        "mimeType": _MIME.get(ext, "application/octet-stream"),
        "sizeBytes": os.path.getsize(path),
    }


def _result_payloads(summary: RunSummary, cases: list[PlanCase]) -> list[dict[str, object]]:
    ref_by_id = {c.id: c.source_ref for c in cases}
    out: list[dict[str, object]] = []
    for r in summary.results:
        artifacts = [
            a
            for a in (_artifact(r.video_path, "VIDEO"), _artifact(r.screenshot_path, "SCREENSHOT"))
            if a is not None
        ]
        out.append(
            {
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
    client = SuitestClient(
        config.publish.api_url,
        token=config.publish.token or None,
        workspace_id=config.publish.workspace_id or None,
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
                results=_result_payloads(summary, cases),
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
