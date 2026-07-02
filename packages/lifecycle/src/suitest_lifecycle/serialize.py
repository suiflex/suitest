"""JSON serialisation for lifecycle artifacts (TestSprite-compatible shapes)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from suitest_lifecycle.models import (
        CodeSummary,
        PlanCase,
        Prd,
        RunSummary,
        TestResult,
    )

JsonValue = object  # documented alias; concrete dicts/lists below are fully typed


def prd_to_json(prd: Prd) -> dict[str, object]:
    return {
        "meta": {"project": prd.project, "date": prd.date, "prepared_by": prd.prepared_by},
        "product_overview": prd.product_overview,
        "core_goals": list(prd.core_goals),
        "features": [
            {"name": f.name, "description": f.description, "user_flows": list(f.user_flows)}
            for f in prd.features
        ],
    }


def plan_to_json(cases: list[PlanCase]) -> list[dict[str, object]]:
    return [
        {
            "id": c.id,
            "title": c.title,
            "description": c.description,
            "category": c.category,
            "priority": c.priority.value,
            "steps": [{"type": s.type, "description": s.description} for s in c.steps],
            "source_ref": c.source_ref,
            "automation_file": c.automation_file,
            "tags": list(c.tags),
        }
        for c in cases
    ]


def code_summary_to_json(summary: CodeSummary) -> dict[str, object]:
    return {
        "project_name": summary.project_name,
        "mode": summary.mode.value,
        "tech_stack": list(summary.tech_stack),
        "auth_flow": summary.auth_flow,
        "features": list(summary.features),
        "endpoints": [
            {
                "method": e.method,
                "path": e.path,
                "auth_required": e.auth_required,
                "source_file": e.source_file,
                "handler": e.handler,
            }
            for e in summary.endpoints
        ],
        "pages": [
            {
                "route": p.route,
                "name": p.name,
                "protected": p.protected,
                "source_file": p.source_file,
            }
            for p in summary.pages
        ],
    }


def result_to_json(r: TestResult) -> dict[str, object]:
    return {
        "testId": r.test_id,
        "title": r.title,
        "description": r.description,
        "status": r.status.value,
        "durationMs": r.duration_ms,
        "error": r.error,
        "automationFile": r.automation_file,
        "artifacts": list(r.artifacts),
        "video": r.video_path,
        "screenshot": r.screenshot_path,
        "steps": [
            {
                "index": s.index,
                "type": s.type,
                "description": s.description,
                "status": s.status.value,
            }
            for s in r.steps
        ],
    }


def results_to_json(results: list[TestResult]) -> list[dict[str, object]]:
    return [result_to_json(r) for r in results]


def summary_to_json(summary: RunSummary) -> dict[str, object]:
    return {
        "project": summary.project,
        "mode": summary.mode.value,
        "baseUrl": summary.base_url,
        "totals": {
            "total": summary.total,
            "passed": summary.passed,
            "failed": summary.failed,
            "skipped": summary.skipped,
            "errored": summary.errored,
        },
        "durationMs": summary.duration_ms,
        "serverStarted": summary.server_started,
        "ready": summary.ready,
        "readyDetail": summary.ready_detail,
        "results": results_to_json(summary.results),
    }


__all__ = [
    "code_summary_to_json",
    "plan_to_json",
    "prd_to_json",
    "results_to_json",
    "summary_to_json",
]
