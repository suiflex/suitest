"""Blackbox reporter — route map, evidence index, bug candidates, summary JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from suitest_lifecycle.blackbox.models import DiscoveryResult


def bug_candidates(discovery: DiscoveryResult) -> list[dict[str, Any]]:
    """Deterministic findings worth a human look — NOT failed tests, DOM smells."""
    out: list[dict[str, Any]] = []
    for p in discovery.pages:
        if p.blank:
            out.append(
                {"route": p.route, "kind": "blank_page", "detail": "page rendered no content"}
            )
        if p.pattern == "error":
            out.append(
                {"route": p.route, "kind": "error_page", "detail": p.visible_text_sample[:160]}
            )
        for err in p.console_errors[:5]:
            out.append({"route": p.route, "kind": "console_error", "detail": err})
        for err in p.network_errors[:5]:
            out.append({"route": p.route, "kind": "network_error", "detail": err})
    if (
        discovery.login is not None
        and discovery.login_probe.attempted
        and not discovery.login_probe.success
    ):
        out.append(
            {
                "route": discovery.login.route,
                "kind": "login_failed",
                "detail": discovery.login_probe.detail,
            }
        )
    return out


def summarize(
    discovery: DiscoveryResult,
    *,
    graph: dict[str, Any] | None = None,
    test_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    routes = {p.route: p.pattern for p in discovery.pages}
    return {
        "baseUrl": discovery.base_url,
        "loginDetected": discovery.login is not None,
        "loginSucceeded": discovery.login_probe.success,
        "routesDiscovered": len(discovery.pages),
        "routeMap": routes,
        "skippedRoutes": discovery.skipped_routes,
        "screenshots": [p.screenshot for p in discovery.pages if p.screenshot],
        "consoleErrorPages": [p.route for p in discovery.pages if p.console_errors],
        "networkErrorPages": [p.route for p in discovery.pages if p.network_errors],
        "bugCandidates": bug_candidates(discovery),
        "graphNodes": len(graph["nodes"]) if graph else None,
        "graphEdges": len(graph["edges"]) if graph else None,
        "testResults": test_results or [],
        "engineErrors": discovery.errors,
    }


def write_report(report: dict[str, Any], out_dir: str | Path) -> str:
    path = Path(out_dir) / "blackbox_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return str(path)


__all__ = ["bug_candidates", "summarize", "write_report"]
