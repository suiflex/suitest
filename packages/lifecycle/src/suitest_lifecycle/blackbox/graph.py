"""Interaction graph — serializable JSON view of the discovered app.

Nodes: page / form / table / modal / action. Edges: navigation / submit /
validation. Zero's generator walks it deterministically; MCP hands it to IDE
agents; LLM mode uses it as reasoning context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from suitest_lifecycle.blackbox.detector import is_destructive
from suitest_lifecycle.blackbox.selector import build_locator, describe

if TYPE_CHECKING:
    from suitest_lifecycle.blackbox.models import DiscoveryResult


def build_graph(discovery: DiscoveryResult) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def node(nid: str, kind: str, **attrs: Any) -> None:
        nodes.append({"id": nid, "kind": kind, **attrs})

    def edge(src: str, dst: str, kind: str, **attrs: Any) -> None:
        edges.append({"from": src, "to": dst, "kind": kind, **attrs})

    for p in discovery.pages:
        pid = f"page:{p.route}"
        node(
            pid,
            "page",
            route=p.route,
            pattern=p.pattern,
            protected=p.protected,
            title=p.title,
            blank=p.blank,
            consoleErrors=len(p.console_errors),
            networkErrors=len(p.network_errors),
        )
        for target in p.nav_routes:
            edge(pid, f"page:{target}", "navigation")
        if p.has_form:
            fid = f"form:{p.route}"
            node(
                fid,
                "form",
                route=p.route,
                fields=[
                    {
                        "label": describe(e),
                        "locator": build_locator(e),
                        "type": e.input_type or e.kind,
                        "required": e.required,
                    }
                    for e in p.inputs
                    if e.input_type not in ("hidden",)
                ][:20],
            )
            submit = next(
                (b for b in p.buttons if not is_destructive(b)),
                None,
            )
            if submit is not None:
                edge(
                    fid,
                    pid,
                    "submit",
                    locator=build_locator(submit),
                    destructive=False,
                )
                edge(fid, pid, "validation", note="empty-required-submit is the safe probe")
        if p.has_table:
            tid = f"table:{p.route}"
            node(tid, "table", route=p.route, rowLocator=p.row_locator)
            edge(pid, tid, "navigation")
        if p.has_modal:
            mid = f"modal:{p.route}"
            node(mid, "modal", route=p.route)
            edge(pid, mid, "navigation")
        for b in p.buttons[:20]:
            if is_destructive(b):
                continue
            aid = f"action:{p.route}:{describe(b)}"
            node(aid, "action", route=p.route, label=describe(b), locator=build_locator(b))
            edge(pid, aid, "navigation")

    if discovery.login is not None:
        edge(
            f"page:{discovery.login.route}",
            f"page:{discovery.login_probe.landed_route or '/'}",
            "submit",
            note="login",
        )

    return {
        "baseUrl": discovery.base_url,
        "nodes": nodes,
        "edges": edges,
        "login": discovery.login.to_json() if discovery.login else None,
        "loginProbe": discovery.login_probe.to_json(),
        "skippedRoutes": discovery.skipped_routes,
    }


__all__ = ["build_graph"]
