"""Lifecycle orchestrator — the analyze → generate → start → wait → run → report loop.

This is the single brain behind both the ``suitest test`` CLI and the MCP
lifecycle tools. It is deterministic (ZERO tier) end to end; LLM enrichment can
later sit on top of analysis/PRD without changing this control flow.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field

from suitest_lifecycle.analyzers.express import analyze_express
from suitest_lifecycle.analyzers.react import analyze_react
from suitest_lifecycle.config import Config, DependencyConfig
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
from suitest_lifecycle.runner import run_tests
from suitest_lifecycle.serialize import (
    code_summary_to_json,
    plan_to_json,
    prd_to_json,
    results_to_json,
)
from suitest_lifecycle.tcm import sync_tcm


@dataclass
class LifecycleResult:
    success: bool
    summary: str
    run: RunSummary | None
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)


def _publish_step(pub: dict[str, object]) -> str:
    if pub.get("published"):
        return f"published to Suitest: run {pub.get('runId')} ({pub.get('imported')} cases imported)"
    return f"publish skipped — {pub.get('reason')}"


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


def _export(config: Config, cases: list[PlanCase], summary: CodeSummary, paths: Paths) -> list[PlanCase]:
    if config.mode is Mode.BACKEND:
        return export_backend_tests(cases, summary, config, paths)
    return export_frontend_tests(cases, summary, config, paths)


def _is_crawl(config: Config) -> bool:
    """Crawl discovery needs the live app, so generation is deferred until after
    the target is ready (unlike repo/openapi which analyze before start)."""
    return config.mode is Mode.FRONTEND and config.analysis_source == "crawl"


def generate_only(
    config: Config, summary: CodeSummary | None = None
) -> tuple[CodeSummary, list[PlanCase], Paths]:
    """Run analyze → PRD → plan → export and write artifacts (no execution).

    ``summary`` may be pre-computed (e.g. from a live DOM crawl that already ran
    after the app came up); otherwise it is analyzed here.
    """
    paths = build_paths(config.output_dir, config.mode)
    paths.ensure()
    if summary is None:
        summary = _analyze(config)
    prd = build_prd(summary, _today(), config.project_name)
    cases = _plan(config, summary)
    cases = enrich_plan(summary, cases, config, resolve_client(config))
    cases = _export(config, cases, summary, paths)

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


def run_lifecycle(config: Config) -> LifecycleResult:
    steps: list[str] = []
    errors: list[str] = []

    crawl_mode = _is_crawl(config)
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
        run_failed = _empty_run(config, summary_code, server_started, False, detail, startup_tail)
        _finalize(config, cases, run_failed, paths)
        if config.publish.enabled:
            steps.append(_publish_step(publish_results(config, run_failed, cases, paths)))
        return LifecycleResult(
            success=False,
            summary=f"FAILED — {detail}",
            run=run_failed,
            artifacts=_artifact_list(paths),
            errors=errors,
            steps=steps,
        )

    try:
        # 1) start dependency services (e.g. the backend a frontend run needs)
        for dep in config.dependencies:
            dpm = ProcessManager()
            dmanaged = dpm.start(dep.start_command, dep.cwd, dep.env)
            dep_managers.append((dep, dpm))
            steps.append(f"started dependency '{dep.name}': {dep.start_command} (pid {dmanaged.popen.pid})")
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
            verdict = wait_until_ready(ready_url, host, config.port, config.server.ready_timeout_sec)
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

        # 4) crawl mode: app is up — discover via live DOM, then generate.
        if crawl_mode:
            from suitest_lifecycle.analyzers.crawl import analyze_crawl

            crawl = analyze_crawl(config.base_url, config.auth.username, config.auth.password)
            steps.append(
                f"crawled {len(crawl.summary.pages)} page(s); "
                f"login {'found' if crawl.login.email else 'not found'}"
            )
            summary_code, cases, paths = generate_only(config, crawl.summary)
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
    if config.publish.enabled:
        steps.append(_publish_step(publish_results(config, run, cases, paths)))

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
