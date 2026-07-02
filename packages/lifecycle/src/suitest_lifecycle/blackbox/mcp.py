"""MCP tool implementations for the blackbox engine.

Each tool takes plain JSON kwargs and returns the standard lifecycle envelope
(``success/summary/data/artifacts/errors``) so IDE agents (Claude Code, Cursor,
Codex) can chain them: discover → graph → generate → run → summarize. State is
persisted as JSON files under the run's output dir, so every stage can also be
called independently in a fresh session.

Config resolution per call: an explicit ``config_path`` (suitest.config.json
with a ``ui`` section) wins; bare ``url``/``username``/``password`` kwargs are
enough for the no-config quick path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from suitest_lifecycle.blackbox.models import BlackboxUiConfig, DiscoveryResult
from suitest_lifecycle.models import Mode
from suitest_lifecycle.paths import Paths, build_paths


def _envelope(
    success: bool,
    summary: str,
    data: dict[str, Any] | None = None,
    artifacts: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "success": success,
        "summary": summary,
        "data": data or {},
        "artifacts": artifacts or [],
        "errors": errors or [],
    }


def _resolve(
    config_path: str = "",
    url: str = "",
    username: str = "",
    password: str = "",
    max_routes: int = 0,
    **_: Any,
) -> tuple[BlackboxUiConfig, Paths]:
    ui = BlackboxUiConfig()
    # Absolute: the runner executes tests with cwd=<test dir>, so a relative
    # output root would double-resolve.
    out_dir = Path("suitest-output").resolve()
    if config_path:
        from suitest_lifecycle.config import load_config

        cfg = load_config(config_path)
        if isinstance(cfg.ui, BlackboxUiConfig):
            ui = cfg.ui
        if not ui.target_url:
            ui.target_url = cfg.base_url
        if not ui.auth.username:
            ui.auth.username = cfg.auth.username
            ui.auth.password = cfg.auth.password
        out_dir = cfg.output_dir
    if url:
        ui.target_url = url.rstrip("/")
    if username:
        ui.auth.username = username
    if password:
        ui.auth.password = password
    if max_routes:
        ui.crawl.max_routes = int(max_routes)
    if not ui.target_url:
        raise ValueError("no target: pass url=… or a config_path with ui.targetUrl/baseUrl")
    paths = build_paths(out_dir, Mode.FRONTEND)
    paths.ensure()
    return ui, paths


def _evidence_dir(paths: Paths) -> Path:
    return paths.tmp_dir / "blackbox"


def _save_discovery(paths: Paths, discovery: DiscoveryResult) -> str:
    p = paths.tmp_dir / "discovery.json"
    p.write_text(json.dumps(discovery.to_json(), indent=2), encoding="utf-8")
    return str(p)


def _load_discovery(paths: Paths) -> DiscoveryResult | None:
    p = paths.tmp_dir / "discovery.json"
    if not p.is_file():
        return None
    return DiscoveryResult.from_json(json.loads(p.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #


def blackbox_discover_app(**kwargs: Any) -> dict[str, Any]:
    """Full discovery: detect login, log in, crawl, capture evidence, save JSON."""
    from suitest_lifecycle.blackbox.crawler import discover
    from suitest_lifecycle.blackbox.graph import build_graph
    from suitest_lifecycle.blackbox.reporter import summarize, write_report

    ui, paths = _resolve(**kwargs)
    discovery = discover(ui, _evidence_dir(paths))
    disc_path = _save_discovery(paths, discovery)
    graph = build_graph(discovery)
    graph_path = paths.tmp_dir / "interaction_graph.json"
    graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    report_path = write_report(summarize(discovery, graph=graph), paths.reports_dir)
    return _envelope(
        success=not discovery.errors,
        summary=(
            f"discovered {len(discovery.pages)} route(s); "
            f"login {'ok' if discovery.login_probe.success else ('detected' if discovery.login else 'not found')}"
        ),
        data=summarize(discovery, graph=graph),
        artifacts=[disc_path, str(graph_path), report_path],
        errors=discovery.errors,
    )


def blackbox_detect_login(**kwargs: Any) -> dict[str, Any]:
    """Detect the login form on the target's login page (no credentials needed)."""
    from suitest_lifecycle.blackbox.crawler import analyze_single_page
    from suitest_lifecycle.blackbox.detector import detect_login_form

    ui, paths = _resolve(**kwargs)
    page = analyze_single_page(ui, ui.auth.login_url or "/login", _evidence_dir(paths))
    form = detect_login_form(page, ignore_testids=ui.crawl.ignore_testids)
    return _envelope(
        success=form.found(),
        summary="login form detected" if form.found() else "no login form found",
        data={"login": form.to_json(), "pattern": page.pattern},
        artifacts=[page.screenshot] if page.screenshot else [],
    )


def blackbox_perform_login(**kwargs: Any) -> dict[str, Any]:
    """Detect + actually perform the login; report where the app landed."""
    from suitest_lifecycle.blackbox.crawler import discover

    ui, paths = _resolve(**kwargs)
    ui.crawl.max_routes = 2  # login page + landing page only
    discovery = discover(ui, _evidence_dir(paths))
    probe = discovery.login_probe
    return _envelope(
        success=probe.success,
        summary=(
            f"login {'succeeded' if probe.success else 'failed'}"
            + (f" — landed on {probe.landed_route}" if probe.landed_route else "")
        ),
        data={
            "login": discovery.login.to_json() if discovery.login else None,
            "probe": probe.to_json(),
        },
    )


def blackbox_crawl_routes(**kwargs: Any) -> dict[str, Any]:
    """Login + BFS crawl; returns the route map (alias of discover, data-focused)."""
    result = blackbox_discover_app(**kwargs)
    data = result.get("data", {})
    return _envelope(
        success=bool(result.get("success")),
        summary=f"crawled {data.get('routesDiscovered', 0)} route(s)",
        data={
            "routeMap": data.get("routeMap", {}),
            "skippedRoutes": data.get("skippedRoutes", []),
        },
        artifacts=list(result.get("artifacts", [])),
        errors=list(result.get("errors", [])),
    )


def blackbox_analyze_page(**kwargs: Any) -> dict[str, Any]:
    """Analyze one page/route: pattern classification + interactive elements."""
    from suitest_lifecycle.blackbox.crawler import analyze_single_page

    page_url = str(kwargs.pop("page_url", "") or kwargs.pop("route", "") or "/")
    ui, paths = _resolve(**kwargs)
    page = analyze_single_page(ui, page_url, _evidence_dir(paths))
    return _envelope(
        success=not page.blank,
        summary=f"{page.route}: pattern={page.pattern}",
        data=page.to_json(),
        artifacts=[page.screenshot] if page.screenshot else [],
    )


def blackbox_build_interaction_graph(**kwargs: Any) -> dict[str, Any]:
    """Build the interaction graph from the saved discovery artifact."""
    from suitest_lifecycle.blackbox.graph import build_graph

    _, paths = _resolve(**kwargs)
    discovery = _load_discovery(paths)
    if discovery is None:
        return _envelope(False, "no discovery.json — run blackbox_discover_app first")
    graph = build_graph(discovery)
    graph_path = paths.tmp_dir / "interaction_graph.json"
    graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    return _envelope(
        True,
        f"graph: {len(graph['nodes'])} node(s), {len(graph['edges'])} edge(s)",
        data=graph,
        artifacts=[str(graph_path)],
    )


def blackbox_generate_playwright_tests(**kwargs: Any) -> dict[str, Any]:
    """Generate Playwright tests from the saved discovery.

    Deterministic baseline always; pass ``prd_file`` (markdown) to append
    PRD-driven semantic cases via the workspace LLM (TestSprite-parity flow).
    """
    from suitest_lifecycle.blackbox.generator import export_blackbox_tests
    from suitest_lifecycle.serialize import plan_to_json

    prd_file = str(kwargs.pop("prd_file", "") or "")
    ui, paths = _resolve(**kwargs)
    discovery = _load_discovery(paths)
    if discovery is None:
        return _envelope(False, "no discovery.json — run blackbox_discover_app first")
    llm = None
    prd_context = ""
    if prd_file:
        from suitest_lifecycle.blackbox.prd_ingest import load_prd
        from suitest_lifecycle.llm_bridge import RemoteLlmClient
        import os as _os

        prd_doc = load_prd(prd_file)
        (paths.tmp_dir / "prd_ingest.json").write_text(
            json.dumps(prd_doc.to_json(), indent=2), encoding="utf-8"
        )
        prd_context = prd_doc.as_prompt_context()
        api_url = _os.environ.get("SUITEST_API_URL", "")
        token = _os.environ.get("SUITEST_API_KEY", "")
        if api_url and token:
            llm = RemoteLlmClient(api_url, token)
    cases = export_blackbox_tests(discovery, ui, paths, llm=llm, prd_context=prd_context)
    paths.test_plan_json.write_text(json.dumps(plan_to_json(cases), indent=2), encoding="utf-8")
    manifest = [
        {"id": c.id, "title": c.title, "file": c.automation_file} for c in cases
    ]
    (paths.tmp_dir / "blackbox_cases.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return _envelope(
        True,
        f"generated {len(cases)} test case(s)",
        data={"cases": manifest},
        artifacts=[str(paths.test_file(str(c.automation_file))) for c in cases],
    )


def blackbox_run_playwright_tests(**kwargs: Any) -> dict[str, Any]:
    """Execute the generated tests; returns per-case outcomes + evidence."""
    from suitest_lifecycle.models import PlanCase, Priority
    from suitest_lifecycle.runner import run_tests
    from suitest_lifecycle.serialize import results_to_json

    _, paths = _resolve(**kwargs)
    manifest_path = paths.tmp_dir / "blackbox_cases.json"
    if not manifest_path.is_file():
        return _envelope(
            False, "no generated tests — run blackbox_generate_playwright_tests first"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = [
        PlanCase(
            id=str(m["id"]),
            title=str(m["title"]),
            description="",
            category="Blackbox",
            priority=Priority.MEDIUM,
            source_ref="bb:run",
            steps=[],
            automation_file=str(m["file"]),
        )
        for m in manifest
    ]
    results = run_tests(cases, paths.mode_dir, selected_ids=None, timeout_sec=120)
    payload = results_to_json(results)
    (paths.tmp_dir / "blackbox_results.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    passed = sum(1 for r in results if r.status.value == "PASSED")

    # Publishing is not optional: when the MCP server carries Suitest
    # credentials (SUITEST_API_URL/KEY), every run lands in the web TCM.
    # A publish failure fails the tool — results must never stay local silently.
    import os as _os

    publish_summary = "publish skipped — SUITEST_API_URL/KEY not set"
    publish_ok = True
    if _os.environ.get("SUITEST_API_URL") and _os.environ.get("SUITEST_API_KEY"):
        pub = blackbox_publish_results(**kwargs)
        publish_ok = bool(pub.get("success"))
        publish_summary = str(pub.get("summary"))
    return _envelope(
        passed == len(results) and publish_ok,
        f"{passed}/{len(results)} passed; {publish_summary}",
        data={"results": payload, "publish": publish_summary},
        artifacts=[str(paths.tmp_dir / "blackbox_results.json")],
    )


def blackbox_collect_evidence(**kwargs: Any) -> dict[str, Any]:
    """Index every evidence artifact produced so far."""
    _, paths = _resolve(**kwargs)
    ev = _evidence_dir(paths)
    shots = sorted(str(p) for p in ev.glob("*.png")) if ev.is_dir() else []
    videos = sorted(str(p) for p in (paths.tmp_dir / "videos").rglob("*.webm"))
    traces = sorted(str(p) for p in paths.tmp_dir.rglob("*.zip"))
    jsons = [
        str(p)
        for p in (
            paths.tmp_dir / "discovery.json",
            paths.tmp_dir / "interaction_graph.json",
            paths.tmp_dir / "blackbox_results.json",
            paths.reports_dir / "blackbox_report.json",
        )
        if p.is_file()
    ]
    return _envelope(
        True,
        f"{len(shots)} screenshot(s), {len(videos)} video(s), {len(jsons)} artifact json(s)",
        data={"screenshots": shots, "videos": videos, "traces": traces, "reports": jsons},
        artifacts=[*shots, *videos, *jsons],
    )


def blackbox_summarize_findings(**kwargs: Any) -> dict[str, Any]:
    """Route map + bug candidates + test outcomes, one JSON for agent reasoning."""
    from suitest_lifecycle.blackbox.graph import build_graph
    from suitest_lifecycle.blackbox.reporter import summarize, write_report

    _, paths = _resolve(**kwargs)
    discovery = _load_discovery(paths)
    if discovery is None:
        return _envelope(False, "no discovery.json — run blackbox_discover_app first")
    results_path = paths.tmp_dir / "blackbox_results.json"
    results = (
        json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else []
    )
    report = summarize(discovery, graph=build_graph(discovery), test_results=results)
    report_path = write_report(report, paths.reports_dir)
    return _envelope(
        True,
        f"{report['routesDiscovered']} route(s), "
        f"{len(report['bugCandidates'])} bug candidate(s)",
        data=report,
        artifacts=[report_path],
    )


def bootstrap_project(**kwargs: Any) -> dict[str, Any]:
    """TestSprite-style setup: open a browser wizard, wait for the user to fill
    target URL / credentials / crawl scope / optional PRD, write
    suitest.config.json into the project. Blocks until submitted."""
    from suitest_lifecycle.blackbox.bootstrap import run_bootstrap_wizard

    project_path = str(kwargs.get("project_path", ".") or ".")
    timeout = int(kwargs.get("timeout_sec", 600) or 600)
    result = run_bootstrap_wizard(project_path, timeout_sec=timeout)
    if not result:
        return _envelope(
            False,
            f"setup form was not submitted within {timeout}s",
            errors=["bootstrap timeout — ask the user to rerun and fill the form"],
        )
    return _envelope(
        True,
        f"config saved: {result['configPath']}"
        + (" (with PRD)" if result.get("prdFile") else ""),
        data=result,
        artifacts=[result["configPath"]],
    )


_PRIO_TO_P = {"High": "P1", "Medium": "P2", "Low": "P3"}


def blackbox_publish_results(**kwargs: Any) -> dict[str, Any]:
    """Publish the blackbox suite + latest run (with video/screenshot evidence)
    to the Suitest server so it shows up in the web TCM (Cases + Runs).

    Needs ``project_id`` (or config publish.projectId) and the usual
    ``SUITEST_API_URL``/``SUITEST_API_KEY`` env the MCP server already carries.
    """
    import os as _os

    import re as _re

    project_id = str(kwargs.pop("project_id", "") or "")
    suite_name = str(kwargs.pop("suite_name", "") or "")
    config_path = str(kwargs.get("config_path", "") or "")
    ui, paths = _resolve(**kwargs)
    if config_path and not project_id:
        from suitest_lifecycle.config import load_config

        cfg = load_config(config_path)
        project_id = cfg.publish.project_id
    # No project configured → the server finds-or-creates one by a slug derived
    # from the target host. Publishing is MANDATORY in the blackbox pipeline;
    # "no project yet" is not an excuse to keep results local.
    host = ui.target_url.split("//")[-1].split("/")[0].removeprefix("www.")
    project_slug = _re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")[:64] or "blackbox"
    project_name = host or "Blackbox"
    api_url = _os.environ.get("SUITEST_API_URL", "")
    token = _os.environ.get("SUITEST_API_KEY", "")
    if not api_url or not token:
        return _envelope(False, "SUITEST_API_URL / SUITEST_API_KEY not set")
    try:
        from suitest_sdk import SuitestAPIError, SuitestClient
    except ImportError:
        return _envelope(False, "suitest-sdk not installed")

    plan_path = paths.test_plan_json
    if not plan_path.is_file():
        return _envelope(False, "no test plan — run blackbox_generate_playwright_tests first")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    suite = suite_name or f"{ui.target_url.split('//')[-1]} blackbox"

    def _sidecar(case_id: str) -> dict[str, Any]:
        p_ = paths.mode_dir / f"{case_id}.result.json"
        return json.loads(p_.read_text(encoding="utf-8")) if p_.is_file() else {}

    try:
        with SuitestClient(api_url, token=token, timeout=180.0) as client:
            def _up(path: str, mime: str) -> str:
                try:
                    return client.upload_file(path, content_type=mime)
                except Exception:
                    return ""

            cases_payload: list[dict[str, Any]] = []
            results_payload: list[dict[str, Any]] = []
            for c in plan:
                code = ""
                if c.get("automation_file"):
                    fp = paths.test_file(str(c["automation_file"]))
                    if fp.is_file():
                        code = fp.read_text(encoding="utf-8")
                cases_payload.append(
                    {
                        "sourceRef": c.get("source_ref", "bb:blackbox"),
                        "name": c["title"],
                        "slug": c["title"],
                        "description": c.get("description", ""),
                        "source": "MCP",
                        "priority": _PRIO_TO_P.get(str(c.get("priority")), "P2"),
                        "category": c.get("category", "Blackbox"),
                        "tags": ["blackbox"],
                        "automationFilePath": c.get("automation_file", ""),
                        "automationCode": code,
                        "generatedBy": "suitest-blackbox",
                        "steps": [
                            {
                                "order": i + 1,
                                "action": st["description"],
                                "expected": st["description"] if st["type"] == "assertion" else "",
                            }
                            for i, st in enumerate(c.get("steps", []))
                        ],
                    }
                )
                side = _sidecar(str(c["id"]))
                if not side:
                    continue
                video = side.get("video") or ""
                artifacts = (
                    [
                        {
                            "kind": "VIDEO",
                            "url": _up(video, "video/webm") or "file://" + video,
                            "mimeType": "video/webm",
                            "sizeBytes": Path(video).stat().st_size if Path(video).is_file() else 0,
                        }
                    ]
                    if video and Path(video).is_file()
                    else []
                )
                results_payload.append(
                    {
                        "name": c["title"],
                        "slug": c["title"],
                        "sourceRef": c.get("source_ref", ""),
                        "outcome": str(side.get("status", "PASSED")),
                        "durationMs": 0,
                        "error": str(side.get("error", "")),
                        "steps": [
                            {
                                "order": st.get("index", i + 1),
                                "type": st.get("type", "action"),
                                "description": st.get("description", ""),
                                "outcome": st.get("status", "PASSED"),
                                "screenshot": (
                                    _up(st["screenshot"], "image/png")
                                    if st.get("screenshot") and Path(st["screenshot"]).is_file()
                                    else ""
                                ),
                            }
                            for i, st in enumerate(side.get("steps", []))
                        ],
                        "artifacts": artifacts,
                    }
                )
            imported = client.bulk_import_cases(
                project_id=project_id,
                project_slug=project_slug,
                project_name=project_name,
                suite_name=suite,
                mode="frontend",
                cases=cases_payload,
            )
            run = client.ingest_run(
                project_id=project_id,
                project_slug=project_slug,
                project_name=project_name,
                suite_name=suite,
                name=f"{suite} run",
                results=results_payload,
            )
    except SuitestAPIError as exc:
        return _envelope(False, f"publish failed: {exc}", errors=[str(exc)])
    return _envelope(
        True,
        f"published: {len(imported.get('imported', []))} case(s), run {run.get('runId')}",
        data={"imported": imported, "run": run},
    )


BLACKBOX_TOOLS = {
    "blackbox_publish_results": blackbox_publish_results,
    "bootstrap_project": bootstrap_project,
    "blackbox_discover_app": blackbox_discover_app,
    "blackbox_detect_login": blackbox_detect_login,
    "blackbox_perform_login": blackbox_perform_login,
    "blackbox_crawl_routes": blackbox_crawl_routes,
    "blackbox_analyze_page": blackbox_analyze_page,
    "blackbox_build_interaction_graph": blackbox_build_interaction_graph,
    "blackbox_generate_playwright_tests": blackbox_generate_playwright_tests,
    "blackbox_run_playwright_tests": blackbox_run_playwright_tests,
    "blackbox_collect_evidence": blackbox_collect_evidence,
    "blackbox_summarize_findings": blackbox_summarize_findings,
}

__all__ = ["BLACKBOX_TOOLS", *BLACKBOX_TOOLS.keys()]
