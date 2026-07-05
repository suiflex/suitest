"""Structured lifecycle tools — the agent-facing surface.

Each tool returns the same envelope so an agent (or the MCP server) gets
predictable, machine-parseable output::

    {"success": bool, "summary": str, "data": {...}, "artifacts": [...], "errors": [...]}

These wrap the orchestrator; they never raise for expected failures (bad config,
target not ready) — those become ``success=false`` envelopes with ``errors``.
"""

from __future__ import annotations

from suitest_lifecycle.blackbox.mcp import BLACKBOX_TOOLS
from suitest_lifecycle.config import ConfigError, load_config
from suitest_lifecycle.models import Mode
from suitest_lifecycle.orchestrator import LifecycleResult, generate_only, run_lifecycle
from suitest_lifecycle.paths import Paths, build_paths
from suitest_lifecycle.serialize import (
    code_summary_to_json,
    plan_to_json,
    summary_to_json,
)


def _envelope(
    success: bool,
    summary: str,
    data: dict[str, object] | None = None,
    artifacts: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict[str, object]:
    return {
        "success": success,
        "summary": summary,
        "data": data or {},
        "artifacts": artifacts or [],
        "errors": errors or [],
    }


def _safe_load(config_path: str) -> tuple[object, dict[str, object] | None]:
    try:
        return load_config(config_path), None
    except (ConfigError, OSError) as exc:
        return None, _envelope(False, f"config error: {exc}", errors=[str(exc)])


def analyze_project(config_path: str) -> dict[str, object]:
    """Static-analyze the target; return endpoints/pages without generating."""
    cfg, err = _safe_load(config_path)
    if err is not None:
        return err
    from suitest_lifecycle.analyzers.express import analyze_express
    from suitest_lifecycle.analyzers.react import analyze_react

    summary = (
        analyze_express(cfg.project_path, cfg.project_name)  # type: ignore[union-attr]
        if cfg.mode is Mode.BACKEND  # type: ignore[union-attr]
        else analyze_react(cfg.project_path, cfg.project_name)  # type: ignore[union-attr]
    )
    label = (
        f"{len(summary.endpoints)} endpoints"
        if summary.mode is Mode.BACKEND
        else f"{len(summary.pages)} pages"
    )
    return _envelope(
        True, f"analyzed {summary.mode.value}: {label}", data=code_summary_to_json(summary)
    )


def _change_report(paths: Paths) -> dict[str, object]:
    import json

    p = paths.tmp_dir / "change_report.json"
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except ValueError:
        return {}


def generate_test_cases(config_path: str) -> dict[str, object]:
    """analyze → PRD → plan → export runnable files (no execution)."""
    cfg, err = _safe_load(config_path)
    if err is not None:
        return err
    _summary, cases, paths = generate_only(cfg)  # type: ignore[arg-type]
    artifacts = [str(paths.prd_json), str(paths.test_plan_json), str(paths.code_summary_json)]
    artifacts += [str(paths.test_file(c.automation_file)) for c in cases if c.automation_file]
    return _envelope(
        True,
        f"generated {len(cases)} test case(s) for {cfg.mode.value}",  # type: ignore[union-attr]
        data={"cases": plan_to_json(cases), **_change_report(paths)},
        artifacts=artifacts,
    )


def generate_backend_tests(config_path: str) -> dict[str, object]:
    return _mode_guarded_generate(config_path, Mode.BACKEND)


def generate_frontend_tests(config_path: str) -> dict[str, object]:
    return _mode_guarded_generate(config_path, Mode.FRONTEND)


def _mode_guarded_generate(config_path: str, expected: Mode) -> dict[str, object]:
    cfg, err = _safe_load(config_path)
    if err is not None:
        return err
    if cfg.mode is not expected:  # type: ignore[union-attr]
        return _envelope(
            False,
            f"config mode is {cfg.mode.value}, expected {expected.value}",  # type: ignore[union-attr]
            errors=["mode mismatch"],
        )
    return generate_test_cases(config_path)


def run_backend_tests(config_path: str, recreate_project: bool = False) -> dict[str, object]:
    return _run_guarded(config_path, Mode.BACKEND, recreate_project)


def run_frontend_tests(config_path: str, recreate_project: bool = False) -> dict[str, object]:
    return _run_guarded(config_path, Mode.FRONTEND, recreate_project)


def _run_result(result: LifecycleResult) -> dict[str, object]:
    data = summary_to_json(result.run) if result.run else {}
    if result.retest:
        data["retest"] = result.retest
    return _envelope(
        result.success,
        result.summary,
        data=data,
        artifacts=result.artifacts,
        errors=result.errors,
    )


def _run_guarded(
    config_path: str, expected: Mode, recreate_project: bool = False
) -> dict[str, object]:
    cfg, err = _safe_load(config_path)
    if err is not None:
        return err
    if cfg.mode is not expected:  # type: ignore[union-attr]
        return _envelope(
            False,
            f"config mode is {cfg.mode.value}, expected {expected.value}",  # type: ignore[union-attr]
            errors=["mode mismatch"],
        )
    if recreate_project:
        cfg.publish.recreate = True  # type: ignore[union-attr]
    result = run_lifecycle(cfg)  # type: ignore[arg-type]
    return _run_result(result)


def run_tests(config_path: str, recreate_project: bool = False) -> dict[str, object]:
    """Mode-agnostic full lifecycle run."""
    cfg, err = _safe_load(config_path)
    if err is not None:
        return err
    if recreate_project:
        cfg.publish.recreate = True  # type: ignore[union-attr]
    result = run_lifecycle(cfg)  # type: ignore[arg-type]
    return _run_result(result)


def generate_report(config_path: str) -> dict[str, object]:
    """Re-emit reports from the last run's stored summary.json (no re-run)."""
    cfg, err = _safe_load(config_path)
    if err is not None:
        return err
    paths = build_paths(cfg.output_dir, cfg.mode)  # type: ignore[union-attr]
    summary_json = paths.reports_dir / "summary.json"
    if not summary_json.is_file():
        return _envelope(
            False, "no prior run found — run the lifecycle first", errors=["summary.json missing"]
        )
    return _envelope(
        True,
        f"report available at {paths.reports_dir}",
        artifacts=[
            str(paths.reports_dir / "summary.md"),
            str(paths.reports_dir / "summary.json"),
            str(paths.reports_dir / "summary.html"),
            str(paths.raw_report_md),
        ],
    )


def sync_tcm(config_path: str) -> dict[str, object]:
    """Report the TCM mirror location and case/run counts."""
    import json

    cfg, err = _safe_load(config_path)
    if err is not None:
        return err
    paths = build_paths(cfg.output_dir, cfg.mode)  # type: ignore[union-attr]
    cases = (
        json.loads(paths.tcm_cases_json.read_text("utf-8"))
        if paths.tcm_cases_json.is_file()
        else []
    )
    runs = (
        json.loads(paths.tcm_runs_json.read_text("utf-8")) if paths.tcm_runs_json.is_file() else []
    )
    return _envelope(
        True,
        f"TCM mirror: {len(cases)} case(s), {len(runs)} run(s)",
        data={"cases": len(cases), "runs": len(runs)},
        artifacts=[str(paths.tcm_cases_json), str(paths.tcm_runs_json)],
    )


def get_failure_context(config_path: str) -> dict[str, object]:
    """Agent-readable failure bundle from the last LOCAL run (spec P0 #4).

    No re-run: reads the stored ``reports/summary.json``. No prior run -> a clear
    error envelope. Prior run but no failures -> success with empty context.
    """
    from suitest_lifecycle.failure_context import build_failure_markdown, load_failed_cases

    cfg, err = _safe_load(config_path)
    if err is not None:
        return err
    paths = build_paths(cfg.output_dir, cfg.mode)  # type: ignore[union-attr]
    if not (paths.reports_dir / "summary.json").is_file():
        return _envelope(
            False,
            "no prior run found — run the lifecycle first",
            errors=["summary.json missing"],
        )
    cases = load_failed_cases(cfg.output_dir)  # type: ignore[union-attr]
    if not cases:
        return _envelope(
            True,
            "last run has no failures — nothing to fix",
            data={"failure_context": "", "failed_cases": 0},
        )
    md = build_failure_markdown(cases)
    return _envelope(
        True,
        f"{len(cases)} failing case(s); context ready for repair",
        data={"failure_context": md, "failed_cases": len(cases)},
    )


# Tool registry (name -> callable) used by the MCP server.
TOOLS = {
    "analyze_project": analyze_project,
    "generate_test_cases": generate_test_cases,
    "generate_backend_tests": generate_backend_tests,
    "generate_frontend_tests": generate_frontend_tests,
    "run_backend_tests": run_backend_tests,
    "run_frontend_tests": run_frontend_tests,
    "run_tests": run_tests,
    "sync_tcm": sync_tcm,
    "generate_report": generate_report,
    "get_failure_context": get_failure_context,
    **BLACKBOX_TOOLS,
}

# Blackbox tools take structured kwargs (url/username/…), not just config_path.
KWARG_TOOLS = frozenset(BLACKBOX_TOOLS)


__all__ = ["KWARG_TOOLS", "TOOLS", *TOOLS.keys()]
