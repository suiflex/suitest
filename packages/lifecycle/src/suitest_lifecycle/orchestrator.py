"""Lifecycle orchestrator — the analyze → generate → start → wait → run → report loop.

This is the single brain behind both the ``suitest test`` CLI and the MCP
lifecycle tools. It is deterministic (ZERO tier) end to end; LLM enrichment can
later sit on top of analysis/PRD without changing this control flow.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from suitest_lifecycle.analyzers.express import analyze_express
from suitest_lifecycle.analyzers.react import analyze_react
from suitest_lifecycle.enrich import enrich_plan, resolve_client
from suitest_lifecycle.exporters.backend import export_backend_tests
from suitest_lifecycle.exporters.frontend import export_frontend_tests
from suitest_lifecycle.frontend_runtime import ensure_browser
from suitest_lifecycle.models import CodeSummary, Mode, PlanCase, RunSummary, TestOutcome
from suitest_lifecycle.paths import Paths, build_paths
from suitest_lifecycle.plan import generate_backend_plan
from suitest_lifecycle.plan_frontend import generate_frontend_plan
from suitest_lifecycle.prd import build_prd
from suitest_lifecycle.process import ProcessManager
from suitest_lifecycle.publish import publish_results
from suitest_lifecycle.readiness import wait_until_ready
from suitest_lifecycle.report import write_all_reports
from suitest_lifecycle.retest import (
    BindingResult,
    build_fingerprint,
    can_reuse_generated,
    classify_results,
    diff_fingerprint,
    load_codegen_meta,
    load_snapshot,
    reconcile_codegen,
    resolve_binding,
    save_snapshot,
)
from suitest_lifecycle.runner import run_tests
from suitest_lifecycle.serialize import (
    code_summary_to_json,
    plan_to_json,
    prd_to_json,
    results_to_json,
)
from suitest_lifecycle.tcm import sync_tcm

if TYPE_CHECKING:
    from suitest_lifecycle.config import Config, DependencyConfig


@dataclass
class LifecycleResult:
    success: bool
    summary: str
    run: RunSummary | None
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    # Retest telemetry: mode, project binding, change detection, generated-code
    # status, failure classification, next actions. Surfaced verbatim in the
    # MCP envelope so agents can reason about WHY a retest behaved as it did.
    retest: dict[str, object] = field(default_factory=dict)


def _publish_step(pub: dict[str, object]) -> str:
    if pub.get("published"):
        return (
            f"published to Suitest: run {pub.get('runId')} ({pub.get('imported')} cases imported)"
        )
    return f"publish skipped — {pub.get('reason')}"


def _record_publish(pub: dict[str, object], steps: list[str], errors: list[str]) -> None:
    """A failed publish never fails the run, but it must be LOUD: agents only
    read the envelope's ``errors``, so a steps-only note is effectively silent."""
    msg = _publish_step(pub)
    steps.append(msg)
    if not pub.get("published"):
        errors.append(msg)


def _today() -> str:
    return datetime.date.today().isoformat()


def _now_iso() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _analyze(config: Config) -> CodeSummary:
    if config.mode is Mode.BACKEND:
        if config.analysis_source == "openapi":
            from suitest_lifecycle.analyzers.openapi import analyze_openapi, load_spec

            spec = load_spec(
                url=config.openapi_url, file=config.openapi_file, base_url=config.base_url
            )
            return analyze_openapi(spec, config.project_name)
        if config.analysis_source == "postman":
            from suitest_lifecycle.analyzers.postman import analyze_postman, load_collection

            return analyze_postman(load_collection(config.postman_file), config.project_name)
        return analyze_express(config.project_path, config.project_name)
    return analyze_react(config.project_path, config.project_name)


def _plan(config: Config, summary: CodeSummary) -> list[PlanCase]:
    if config.mode is Mode.BACKEND:
        return generate_backend_plan(summary)
    return generate_frontend_plan(summary, config)


def _export(
    config: Config,
    cases: list[PlanCase],
    summary: CodeSummary,
    paths: Paths,
    *,
    llm: object | None = None,
    dom_context: str = "",
) -> list[PlanCase]:
    if config.mode is Mode.BACKEND:
        return export_backend_tests(cases, summary, config, paths)
    return export_frontend_tests(cases, summary, config, paths, llm=llm, dom_context=dom_context)


def _is_crawl(config: Config) -> bool:
    """Crawl discovery needs the live app, so generation is deferred until after
    the target is ready (unlike repo/openapi which analyze before start)."""
    return config.mode is Mode.FRONTEND and config.analysis_source == "crawl"


def _is_blackbox(config: Config) -> bool:
    """Blackbox DOM engine (no repo, no LLM) — also deferred until the app is up."""
    return config.mode is Mode.FRONTEND and config.analysis_source == "blackbox"


# Stable identity fields for a discovered element — deliberately EXCLUDES
# volatile data (screenshot paths, dynamic visible text) so a retest against an
# unchanged app never false-positives as a UI change.
_ELEMENT_ID_FIELDS = (
    "kind",
    "testid",
    "role",
    "name",
    "label",
    "placeholder",
    "dom_id",
    "css",
    "input_type",
)


def _crawl_elements(crawl: object | None) -> dict[str, object] | None:
    """Per-route interactive-element identity from a live DOM crawl.

    Feeds selector-level change detection (``selector_changed``). Returns None
    when no crawl ran (repo-analysis runs have no element capture)."""
    if crawl is None:
        return None
    page_elements = getattr(crawl, "page_elements", None)
    page_testids = getattr(crawl, "page_testids", None)
    pe = page_elements if isinstance(page_elements, dict) else {}
    pt = page_testids if isinstance(page_testids, dict) else {}
    if not pe and not pt:
        return None
    return {
        str(route): {"elements": pe.get(route), "testids": pt.get(route)}
        for route in sorted({*pe, *pt})
    }


def _discovery_elements(pages: list[object]) -> dict[str, object]:
    """Per-route element identity from a blackbox discovery (same purpose as
    :func:`_crawl_elements`, different source shape)."""

    def _ident(e: object, *, with_text: bool = False) -> dict[str, object]:
        d: dict[str, object] = {f: getattr(e, f, "") for f in _ELEMENT_ID_FIELDS}
        if with_text:
            # Button labels are part of the UI contract (button_label_changed);
            # link/input text is too dynamic to fingerprint.
            d["text"] = getattr(e, "text", "")
        return d

    out: dict[str, object] = {}
    for p in pages:
        out[str(getattr(p, "route", ""))] = {
            "inputs": [_ident(e) for e in getattr(p, "inputs", [])],
            "buttons": [_ident(e, with_text=True) for e in getattr(p, "buttons", [])],
            "links": [_ident(e) for e in getattr(p, "links", [])],
            "hasTable": getattr(p, "has_table", False),
            "hasForm": getattr(p, "has_form", False),
            "hasModal": getattr(p, "has_modal", False),
            "rowLocator": getattr(p, "row_locator", ""),
        }
    return out


def generate_only(
    config: Config,
    summary: CodeSummary | None = None,
    *,
    crawl: object | None = None,
) -> tuple[CodeSummary, list[PlanCase], Paths]:
    """Run analyze → PRD → plan → export and write artifacts (no execution).

    ``summary`` may be pre-computed (e.g. from a live DOM crawl that already ran
    after the app came up); otherwise it is analyzed here. ``crawl`` is the
    optional :class:`CrawlResult` whose DOM digest powers LLM codegen for apps
    with no data-testid convention.
    """
    paths = build_paths(config.output_dir, config.mode)
    paths.ensure()
    if summary is None:
        summary = _analyze(config)
    prd = build_prd(summary, _today(), config.project_name)
    cases = _plan(config, summary)
    client = resolve_client(config)
    cases = enrich_plan(summary, cases, config, client)
    # LLM codegen wants a client even when enrichment is off — resolve the
    # remote bridge directly unless codegen is pinned deterministic.
    codegen_llm = client
    if codegen_llm is None and config.mode is Mode.FRONTEND and config.codegen != "deterministic":
        from suitest_lifecycle.llm_bridge import resolve_remote

        codegen_llm = resolve_remote(config)
    from suitest_lifecycle.llm_bridge import build_dom_context

    dom_context = build_dom_context(crawl, summary)  # type: ignore[arg-type]

    # --- retest: change detection + generated-code reuse -------------------- #
    import hashlib

    fingerprint = build_fingerprint(summary, cases, _crawl_elements(crawl))
    change_report = diff_fingerprint(load_snapshot(paths), fingerprint)
    dom_digest = hashlib.sha256(dom_context.encode("utf-8")).hexdigest()[:16]
    meta_prev = load_codegen_meta(paths)
    reuse = (
        not change_report["first"]
        and not change_report["changed"]
        and can_reuse_generated(cases, paths, meta_prev, dom_digest, config.codegen)
    )
    export_error = ""
    stash: dict[str, str] = {}
    if not reuse:
        # Stash current files so a regen never silently destroys reviewed code:
        # changed files are archived to history/, a failed regen is rolled back.
        for entry in meta_prev.values():
            fname = str(entry.get("file", ""))
            fp = paths.test_file(fname) if fname else None
            if fp is not None and fp.is_file():
                stash[fname] = fp.read_text(encoding="utf-8")
        try:
            cases = _export(config, cases, summary, paths, llm=codegen_llm, dom_context=dom_context)
        except Exception as exc:  # regen failure → keep prior code, flag needs_review
            export_error = f"{type(exc).__name__}: {exc}"
            for fname, content in stash.items():
                paths.test_file(fname).write_text(content, encoding="utf-8")
            for c in cases:
                prev_entry = meta_prev.get(c.title)
                if prev_entry:
                    c.automation_file = str(prev_entry.get("file", ""))
    _meta, gen_counts = reconcile_codegen(
        cases,
        paths,
        meta_prev,
        stash,
        dom_digest,
        config.codegen,
        reused=reuse,
        export_error=export_error,
    )
    save_snapshot(paths, fingerprint)
    (paths.tmp_dir / "change_report.json").write_text(
        json.dumps({"changeDetection": change_report, "generatedCode": gen_counts}, indent=2),
        encoding="utf-8",
    )

    paths.code_summary_json.write_text(json.dumps(code_summary_to_json(summary), indent=2), "utf-8")
    paths.prd_json.write_text(json.dumps(prd_to_json(prd), indent=2), encoding="utf-8")
    paths.test_plan_json.write_text(json.dumps(plan_to_json(cases), indent=2), encoding="utf-8")
    paths.config_snapshot_json.write_text(_config_snapshot(config), encoding="utf-8")
    return summary, cases, paths


def _config_snapshot(config: Config) -> str:
    return json.dumps(
        {
            "mode": config.mode.value,
            "scope": config.scope,
            "projectName": config.project_name,
            "projectPath": str(config.project_path),
            "baseUrl": config.base_url,
            "apiBasePath": config.api_base_path,
            "readyPath": config.ready_path,
            "port": config.port,
            "autostart": config.server.autostart,
            "startCommand": config.server.start_command,
            "testIds": config.test_ids,
        },
        indent=2,
    )


def _blackbox_generate(config: Config) -> tuple[CodeSummary, list[PlanCase], Paths, list[str]]:
    """Blackbox path: discover the live app → graph → deterministic tests.

    Writes discovery.json / interaction_graph.json / blackbox_report.json next
    to the other run artifacts so MCP tools and LLM consumers can pick them up.
    """
    import json as _json

    from suitest_lifecycle.blackbox.crawler import discover
    from suitest_lifecycle.blackbox.generator import export_blackbox_tests
    from suitest_lifecycle.blackbox.graph import build_graph
    from suitest_lifecycle.blackbox.models import BlackboxUiConfig
    from suitest_lifecycle.blackbox.reporter import summarize, write_report
    from suitest_lifecycle.models import Page

    ui = config.ui if isinstance(config.ui, BlackboxUiConfig) else BlackboxUiConfig()
    if not ui.target_url:
        ui.target_url = config.base_url
    if not ui.auth.username:
        ui.auth.username = config.auth.username
        ui.auth.password = config.auth.password

    paths = build_paths(config.output_dir, config.mode)
    paths.ensure()
    evidence_dir = paths.tmp_dir / "blackbox"

    discovery = discover(ui, evidence_dir)
    steps = [
        f"blackbox: discovered {len(discovery.pages)} route(s); "
        f"login {'detected' if discovery.login else 'not found'}"
        + (", login OK" if discovery.login_probe.success else ""),
    ]
    graph = build_graph(discovery)
    (paths.tmp_dir / "discovery.json").write_text(
        _json.dumps(discovery.to_json(), indent=2), encoding="utf-8"
    )
    (paths.tmp_dir / "interaction_graph.json").write_text(
        _json.dumps(graph, indent=2), encoding="utf-8"
    )
    write_report(summarize(discovery, graph=graph), paths.reports_dir)

    prd_context = ""
    llm = None
    if config.prd_file:
        from suitest_lifecycle.blackbox.prd_ingest import load_prd
        from suitest_lifecycle.llm_bridge import resolve_remote

        prd_doc = load_prd(config.prd_file)
        (paths.tmp_dir / "prd_ingest.json").write_text(
            _json.dumps(prd_doc.to_json(), indent=2), encoding="utf-8"
        )
        prd_context = prd_doc.as_prompt_context()
        llm = resolve_remote(config)
        steps.append(
            f"prd: ingested '{prd_doc.title or config.prd_file}' "
            f"({len(prd_doc.requirements)} requirement(s)); "
            f"LLM bridge {'available' if llm else 'unavailable — deterministic only'}"
        )
    cases = export_blackbox_tests(discovery, ui, paths, llm=llm, prd_context=prd_context)
    steps.append(f"blackbox: generated {len(cases)} test case(s)")

    summary = CodeSummary(
        project_name=config.project_name,
        mode=Mode.FRONTEND,
        tech_stack=["Web", "blackbox"],
        pages=[
            Page(route=p.route, name=p.pattern, protected=p.protected, source_file="blackbox")
            for p in discovery.pages
        ],
        features=[p.pattern for p in discovery.pages],
        auth_flow=(
            "Login form discovered via blackbox DOM heuristics."
            if discovery.login
            else "No login form found."
        ),
    )
    # Retest change detection for the blackbox path (deterministic codegen, so
    # code reuse is just hash bookkeeping — no LLM cost to skip).
    fingerprint = build_fingerprint(summary, cases, _discovery_elements(list(discovery.pages)))
    change_report = diff_fingerprint(load_snapshot(paths), fingerprint)
    _meta, gen_counts = reconcile_codegen(
        cases, paths, load_codegen_meta(paths), {}, "", "blackbox"
    )
    save_snapshot(paths, fingerprint)
    (paths.tmp_dir / "change_report.json").write_text(
        _json.dumps({"changeDetection": change_report, "generatedCode": gen_counts}, indent=2),
        encoding="utf-8",
    )

    paths.code_summary_json.write_text(
        _json.dumps(code_summary_to_json(summary), indent=2), encoding="utf-8"
    )
    paths.test_plan_json.write_text(_json.dumps(plan_to_json(cases), indent=2), encoding="utf-8")
    paths.config_snapshot_json.write_text(_config_snapshot(config), encoding="utf-8")
    return summary, cases, paths, steps


def _load_change_report(paths: Paths) -> dict[str, object]:
    p = paths.tmp_dir / "change_report.json"
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except ValueError:
        return {}


_RUN_MODE = {
    "local_only": "local_only",
    "first_setup": "first_test",
    "recreate_requested": "recreate",
    "valid": "retest",
    "repaired": "retest",
    "unverified": "retest",
    "missing": "blocked",
}


def _build_retest(
    binding: BindingResult,
    report: dict[str, object],
    classifications: dict[str, str],
    pub: dict[str, object],
) -> dict[str, object]:
    cd = report.get("changeDetection")
    gc = report.get("generatedCode")
    cd = cd if isinstance(cd, dict) else {}
    gc = gc if isinstance(gc, dict) else {}
    mode = _RUN_MODE.get(binding.status, "retest")
    if mode == "retest" and cd.get("first"):
        mode = "first_test"  # binding valid but this host never generated before
    kinds = sorted(set(classifications.values()))
    stale_raw = pub.get("stale")
    stale = stale_raw if isinstance(stale_raw, list) else []

    next_actions: list[str] = []
    if binding.status == "missing":
        next_actions.append(
            "Fix publish.projectId in suitest.config.json (see candidates), or set "
            "publish.recreateProject=true / re-run with recreate_project to create a new project."
        )
    if stale:
        next_actions.append(f"Review {len(stale)} STALE test case(s) in the TCM: {stale}")
    if kinds:
        next_actions.append("Inspect classified failures: " + ", ".join(kinds))
    if gc.get("needs_review"):
        next_actions.append(
            "Code regeneration failed — prior automation kept; see codegen_meta.json (needs_review)."
        )
    if not next_actions:
        next_actions.append("No action needed — binding resolved and results recorded.")

    return {
        "mode": mode,
        "projectBinding": binding.to_json(),
        "changeDetection": cd,
        "generatedCode": gc,
        "failureClassification": kinds,
        "testCases": {
            "created": pub.get("created", 0),
            "reused": pub.get("reused", 0),
            "stale": len(stale),
        },
        "testRun": {
            "created": bool(pub.get("published")),
            "runId": pub.get("runId"),
            "status": pub.get("runStatus"),
        },
        "published": bool(pub.get("published")),
        "publishReason": str(pub.get("reason", "")),
        "nextActions": next_actions,
    }


def run_lifecycle(config: Config) -> LifecycleResult:
    steps: list[str] = []
    errors: list[str] = []

    # Project binding FIRST: a stale, unrepairable binding must fail loudly
    # before anything is generated, executed, or inserted server-side.
    binding = resolve_binding(config, recreate=config.publish.recreate)
    steps.append(f"project binding: {binding.status} ({binding.action})")
    if binding.detail:
        steps.append(f"binding detail: {binding.detail}")
    if binding.blocks_publish:
        errors.append(binding.detail)
        pub: dict[str, object] = {"published": False, "reason": binding.detail, "blocked": True}
        return LifecycleResult(
            success=False,
            summary=(
                "FAILED — project binding is stale (projectId not found) and could not be "
                "repaired. Nothing was generated, executed, or published."
            ),
            run=None,
            errors=errors,
            steps=steps,
            retest=_build_retest(binding, {}, {}, pub),
        )

    crawl_mode = _is_crawl(config) or _is_blackbox(config)
    summary_code: CodeSummary | None
    if crawl_mode:
        # Discovery needs the live app — defer analyze/generate until after ready.
        paths = build_paths(config.output_dir, config.mode)
        paths.ensure()
        summary_code = None
        cases = []
        steps.append("crawl mode: discovery deferred until target is ready")
    else:
        summary_code, cases, paths = generate_only(config)
        steps.append(f"analyzed {config.mode.value}: {_count_label(summary_code)}")
        steps.append(f"generated {len(cases)} test case(s) + runnable files")

    pm = ProcessManager()
    dep_managers: list[tuple[DependencyConfig, ProcessManager]] = []
    server_started = False
    ready_detail = "autostart disabled — assuming target already running"
    is_ready = True
    startup_tail = ""

    host = "localhost"
    ready_url = config.base_url.rstrip("/") + "/" + config.ready_path.lstrip("/")

    def _finish_fail(detail: str) -> LifecycleResult:
        errors.append(f"not ready: {detail}")
        kind = "dependency_not_ready" if detail.startswith("dependency") else "target_not_ready"
        run_failed = _empty_run(config, summary_code, server_started, False, detail, startup_tail)
        _finalize(config, cases, run_failed, paths)
        fail_pub: dict[str, object] = {"published": False, "reason": "run aborted before tests"}
        if config.publish.enabled:
            fail_pub = publish_results(config, run_failed, cases, paths, binding=binding)
            _record_publish(fail_pub, steps, errors)
        return LifecycleResult(
            success=False,
            summary=f"FAILED — {detail}",
            run=run_failed,
            artifacts=_artifact_list(paths),
            errors=errors,
            steps=steps,
            retest=_build_retest(
                binding, _load_change_report(paths), {"readiness": kind}, fail_pub
            ),
        )

    try:
        # 1) start dependency services (e.g. the backend a frontend run needs)
        for dep in config.dependencies:
            dpm = ProcessManager()
            dmanaged = dpm.start(dep.start_command, dep.cwd, dep.env)
            dep_managers.append((dep, dpm))
            steps.append(
                f"started dependency '{dep.name}': {dep.start_command} (pid {dmanaged.popen.pid})"
            )
            dverdict = wait_until_ready(
                dep.ready_url,
                "localhost",
                dep.port,
                dep.ready_timeout_sec,
                log_reader=dmanaged.log_text,
                ready_log_pattern=dep.ready_log_pattern,
            )
            if not dverdict.ready:
                return _finish_fail(f"dependency '{dep.name}' not ready: {dverdict.detail}")
            steps.append(
                f"dependency '{dep.name}' ready: {dverdict.strategy} ({dverdict.waited_ms} ms)"
            )

        # 2) start the main target (or wait for an already-running one)
        if config.server.autostart:
            cwd = (config.project_path / config.server.cwd).resolve()
            managed = pm.start(config.server.start_command, cwd, config.server.env)
            server_started = True
            steps.append(f"started target: {config.server.start_command} (pid {managed.popen.pid})")
            verdict = wait_until_ready(
                ready_url,
                host,
                config.port,
                config.server.ready_timeout_sec,
                log_reader=managed.log_text,
                ready_log_pattern=config.server.ready_log_pattern,
            )
            is_ready = verdict.ready
            ready_detail = f"{verdict.strategy}: {verdict.detail} ({verdict.waited_ms} ms)"
            startup_tail = managed.tail(40)
            steps.append(f"readiness: {ready_detail}")
        else:
            verdict = wait_until_ready(
                ready_url, host, config.port, config.server.ready_timeout_sec
            )
            is_ready = verdict.ready
            ready_detail = f"{verdict.strategy}: {verdict.detail} ({verdict.waited_ms} ms)"
            steps.append(f"readiness (no autostart): {ready_detail}")

        if not is_ready:
            return _finish_fail(f"target never became ready ({ready_detail})")

        # 3) frontend: ensure Suitest's bundled browser is provisioned (user never
        #    installs playwright themselves — Suitest owns the runtime)
        if config.mode is Mode.FRONTEND:
            browser = ensure_browser()
            steps.append(f"browser: {browser.detail}")
            if not browser.ready:
                return _finish_fail(f"browser unavailable: {browser.detail}")

        # 4) crawl/blackbox mode: app is up — discover via live DOM, then generate.
        if _is_blackbox(config):
            summary_code, cases, paths, bb_steps = _blackbox_generate(config)
            steps.extend(bb_steps)
        elif crawl_mode:
            from suitest_lifecycle.analyzers.crawl import analyze_crawl

            crawl = analyze_crawl(config.base_url, config.auth.username, config.auth.password)
            steps.append(
                f"crawled {len(crawl.summary.pages)} page(s); "
                f"login {'found' if crawl.login.email else 'not found'}"
            )
            summary_code, cases, paths = generate_only(config, crawl.summary, crawl=crawl)
            steps.append(f"generated {len(cases)} test case(s) from crawl")

        results = run_tests(
            cases,
            paths.mode_dir,
            selected_ids=config.test_ids or None,
            timeout_sec=120,
        )
        steps.append(f"executed {len(results)} test(s)")
    finally:
        if server_started:
            pm.stop(config.server.stop_grace_sec)
            steps.append("stopped target server")
        for dep, dpm in reversed(dep_managers):
            dpm.stop(dep.stop_grace_sec)
            steps.append(f"stopped dependency '{dep.name}'")

    run = _build_run(config, summary_code, results, server_started, ready_detail, startup_tail)
    _finalize(config, cases, run, paths)

    report = _load_change_report(paths)
    cd = report.get("changeDetection")
    api_changed = bool(cd.get("apiChanged")) if isinstance(cd, dict) else False
    classifications = classify_results(run.results, config.mode, api_changed=api_changed)
    if classifications:
        steps.append(
            "failure classification: "
            + ", ".join(f"{tid}={kind}" for tid, kind in sorted(classifications.items()))
        )

    pub2: dict[str, object] = {"published": False, "reason": "publish disabled"}
    if config.publish.enabled:
        pub2 = publish_results(
            config, run, cases, paths, binding=binding, classifications=classifications
        )
        _record_publish(pub2, steps, errors)

    ok = run.failed == 0 and run.errored == 0
    verb = "PASSED" if ok else "FAILED"
    return LifecycleResult(
        success=ok,
        summary=(
            f"{verb} — {run.passed}/{run.total} passed "
            f"({run.failed} failed, {run.skipped} skipped) in {run.duration_ms} ms"
        ),
        run=run,
        artifacts=_artifact_list(paths),
        errors=errors,
        steps=steps,
        retest=_build_retest(binding, report, classifications, pub2),
    )


def _finalize(config: Config, cases: list[PlanCase], run: RunSummary, paths: Paths) -> None:
    paths.test_results_json.write_text(
        json.dumps(results_to_json(run.results), indent=2), encoding="utf-8"
    )
    write_all_reports(run, paths, _today())
    sync_tcm(cases, run, paths, config.mode, _now_iso())


def _build_run(
    config: Config,
    summary_code: CodeSummary,
    results: list,  # list[TestResult]
    server_started: bool,
    ready_detail: str,
    startup_tail: str,
) -> RunSummary:
    passed = sum(1 for r in results if r.status is TestOutcome.PASSED)
    failed = sum(1 for r in results if r.status is TestOutcome.FAILED)
    skipped = sum(1 for r in results if r.status is TestOutcome.SKIPPED)
    errored = sum(1 for r in results if r.status is TestOutcome.ERROR)
    duration = sum(r.duration_ms for r in results)
    return RunSummary(
        project=config.project_name,
        mode=config.mode,
        base_url=config.base_url,
        total=len(results),
        passed=passed,
        failed=failed,
        skipped=skipped,
        errored=errored,
        duration_ms=duration,
        results=results,
        server_started=server_started,
        ready=True,
        ready_detail=ready_detail,
        startup_log_tail=startup_tail,
    )


def _empty_run(
    config: Config,
    summary_code: CodeSummary,
    server_started: bool,
    ready: bool,
    ready_detail: str,
    startup_tail: str,
) -> RunSummary:
    return RunSummary(
        project=config.project_name,
        mode=config.mode,
        base_url=config.base_url,
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        errored=0,
        duration_ms=0,
        results=[],
        server_started=server_started,
        ready=ready,
        ready_detail=ready_detail,
        startup_log_tail=startup_tail,
    )


def _count_label(summary: CodeSummary) -> str:
    if summary.mode is Mode.BACKEND:
        return f"{len(summary.endpoints)} endpoints"
    return f"{len(summary.pages)} pages"


def _artifact_list(paths: Paths) -> list[str]:
    candidates = [
        paths.code_summary_json,
        paths.prd_json,
        paths.test_plan_json,
        paths.test_results_json,
        paths.raw_report_md,
        paths.reports_dir / "summary.json",
        paths.reports_dir / "summary.md",
        paths.reports_dir / "summary.html",
        paths.tcm_cases_json,
        paths.tcm_runs_json,
    ]
    return [str(p) for p in candidates if p.exists()]


__all__ = ["LifecycleResult", "generate_only", "run_lifecycle"]
