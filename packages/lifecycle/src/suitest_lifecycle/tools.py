"""Structured lifecycle tools — the agent-facing surface.

Each tool returns the same envelope so an agent (or the MCP server) gets
predictable, machine-parseable output::

    {"success": bool, "summary": str, "data": {...}, "artifacts": [...], "errors": [...]}

These wrap the orchestrator; they never raise for expected failures (bad config,
target not ready) — those become ``success=false`` envelopes with ``errors``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import suppress
from pathlib import Path
from typing import Any

from suitest_lifecycle.blackbox.mcp import BLACKBOX_TOOLS
from suitest_lifecycle.config import Config, ConfigError, load_config
from suitest_lifecycle.fixture_generator import suitest_create_dummy_file
from suitest_lifecycle.interactive_browser import (
    INTERACTIVE_BROWSER_TOOLS,
    _is_sensitive_input,
)
from suitest_lifecycle.models import Mode
from suitest_lifecycle.orchestrator import LifecycleResult, generate_only, run_lifecycle
from suitest_lifecycle.paths import build_paths
from suitest_lifecycle.retest import load_change_report
from suitest_lifecycle.serialize import (
    code_summary_to_json,
    plan_to_json,
    summary_to_json,
)
from suitest_lifecycle.tool_result import envelope as _envelope

logger = logging.getLogger(__name__)


def _safe_load(config_path: str) -> tuple[Config | None, dict[str, object] | None]:
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
        data={"cases": plan_to_json(cases), **load_change_report(paths)},
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
    cases_summary = [
        {
            "title": c.title,
            "failed_step": c.failed_step_index,
            "failed_selector": c.failed_selector,
            "suggested_selectors": c.suggested_selectors,
            "error": c.error_message,
        }
        for c in cases
    ]
    return _envelope(
        True,
        f"{len(cases)} failing case(s); context ready for repair",
        data={
            "failure_context": md,
            "failed_cases": len(cases),
            "cases": cases_summary,
        },
    )


def whitebox_discover_tests(config_path: str) -> dict[str, object]:
    cfg, err = _safe_load(config_path)
    if err is not None:
        return err
    try:
        from suitest_lifecycle.whitebox import discover

        result = discover(cfg)  # type: ignore[arg-type]
    except (OSError, ValueError) as exc:
        return _envelope(False, f"white-box discovery failed: {exc}", errors=[str(exc)])
    return _envelope(
        True,
        f"discovered {len(result.targets)} {result.framework} test target(s)",
        data=result.to_json(cfg.project_path),  # type: ignore[union-attr]
    )


def whitebox_run_tests(config_path: str) -> dict[str, object]:
    cfg, err = _safe_load(config_path)
    if err is not None:
        return err
    cfg.testing.approach = "white-box"  # type: ignore[union-attr]
    return _run_result(run_lifecycle(cfg))  # type: ignore[arg-type]


def _find_target_input(
    upd: dict[str, Any],
    discovered_inputs: list[dict[str, Any]],
    inputs_by_sel: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    step_ord = upd.get("step_order")
    if step_ord is not None and 1 <= int(step_ord) <= len(discovered_inputs):
        return discovered_inputs[int(step_ord) - 1]
    if upd.get("selector"):
        sel_key = str(upd["selector"])
        match = inputs_by_sel.get(sel_key)
        if match is not None:
            return match
        for inp in discovered_inputs:
            if sel_key in str(inp.get("selector", "")):
                return inp
    return None


def edit_test_case_inputs(
    config_path: str = "suitest.config.json",
    case_id: str = "",
    action: str = "get",
    updates: list[dict[str, Any]] | None = None,
    output_dir: str = "",
    **kwargs: Any,
) -> dict[str, object]:
    """Inspect or update input values, file upload paths, and variable bindings in a test case."""
    out_dir = Path(output_dir).resolve() if output_dir else Path("suitest-output").resolve()
    if config_path and not output_dir:
        try:
            cfg = load_config(config_path)
            out_dir = cfg.output_dir
        except (ConfigError, OSError, ValueError) as err:
            logger.debug("Could not read output_dir from config %s: %s", config_path, err)
    paths = build_paths(out_dir, Mode.FRONTEND)
    mode_dir = paths.mode_dir

    if not case_id:
        plan_path = paths.test_plan_json
        cases_summary: list[dict[str, Any]] = []
        if plan_path.is_file():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                for c in plan:
                    cases_summary.append(
                        {
                            "id": c.get("id"),
                            "title": c.get("title"),
                            "file": c.get("automationFile", ""),
                            "stepCount": len(c.get("steps", [])),
                        }
                    )
            except (OSError, json.JSONDecodeError, ValueError) as err:
                logger.debug("Could not read test plan %s: %s", plan_path, err)
        if not cases_summary and mode_dir.is_dir():
            tc_files = sorted(mode_dir.glob("TC*.py"))
            for f in tc_files:
                cases_summary.append({"id": f.stem.split("_")[0], "title": f.stem, "file": f.name})
        return _envelope(
            True,
            f"found {len(cases_summary)} test case(s)",
            data={"cases": cases_summary},
        )

    target_file: Path | None = None
    if mode_dir.is_dir():
        specific_matches = sorted(mode_dir.glob(f"{case_id}_*.py")) or sorted(
            mode_dir.glob(f"{case_id}.py")
        )
        if specific_matches:
            target_file = specific_matches[0]
        else:
            all_py_files = sorted(mode_dir.glob("*.py"))
            case_lower = case_id.lower()
            for candidate in all_py_files:
                if case_lower in candidate.name.lower():
                    target_file = candidate
                    break
    if target_file is None or not target_file.is_file():
        return _envelope(
            False,
            f"test case file for '{case_id}' not found in {mode_dir}",
            errors=[f"file matching {case_id}*.py does not exist"],
        )

    source = target_file.read_text(encoding="utf-8")

    fill_re = re.compile(r"await\s+(.+?)\.fill\((.*?)\)")
    select_re = re.compile(r"await\s+(.+?)\.select_option\((.*?)\)")
    upload_re = re.compile(r"await\s+(.+?)\.set_input_files\((.*?)\)")
    upload_files_var_re = re.compile(r'upload_files\s*=\s*(\[.*?\]|["\'].*?["\'])')

    discovered_inputs: list[dict[str, Any]] = []
    matches: list[tuple[int, dict[str, Any]]] = []

    for m in fill_re.finditer(source):
        loc = m.group(1).strip()
        raw_val = m.group(2).strip()
        val = (
            raw_val[1:-1]
            if raw_val.startswith(('"', "'")) and raw_val.endswith(('"', "'"))
            else raw_val
        )
        input_type = (
            "password" if "password" in loc.lower() or "password" in val.lower() else "text"
        )
        if "captcha" in loc.lower() or "captcha" in val.lower():
            input_type = "solve_captcha"
        matches.append(
            (
                m.start(),
                {
                    "type": input_type,
                    "selector": loc,
                    "current_value": val,
                    "is_multiple": False,
                    "is_variable": val.startswith("{{") and val.endswith("}}"),
                },
            )
        )

    for m in select_re.finditer(source):
        loc = m.group(1).strip()
        raw_val = m.group(2).strip()
        val = (
            raw_val[1:-1]
            if raw_val.startswith(('"', "'")) and raw_val.endswith(('"', "'"))
            else raw_val
        )
        matches.append(
            (
                m.start(),
                {
                    "type": "select",
                    "selector": loc,
                    "current_value": val,
                    "is_multiple": False,
                    "is_variable": val.startswith("{{") and val.endswith("}}"),
                },
            )
        )

    for m in upload_re.finditer(source):
        loc = m.group(1)
        raw_val = m.group(2).strip()
        val_parsed: Any = raw_val
        is_mult = False
        if raw_val.startswith("[") and raw_val.endswith("]"):
            is_mult = True
            try:
                val_parsed = json.loads(raw_val.replace("'", '"'))
            except Exception:
                val_parsed = raw_val
        elif raw_val in ("upload_files",):
            v_match = upload_files_var_re.search(source)
            if v_match:
                v_raw = v_match.group(1).strip()
                if v_raw.startswith("["):
                    is_mult = True
                try:
                    val_parsed = json.loads(v_raw.replace("'", '"'))
                except Exception:
                    val_parsed = v_raw
        elif raw_val.startswith(('"', "'")):
            val_parsed = raw_val[1:-1]
        matches.append(
            (
                m.start(),
                {
                    "type": "file_upload",
                    "selector": loc,
                    "current_value": val_parsed,
                    "is_multiple": is_mult,
                    "is_variable": isinstance(val_parsed, str)
                    and val_parsed.startswith("{{")
                    and val_parsed.endswith("}}"),
                },
            )
        )

    matches.sort(key=lambda x: x[0])
    for idx, (_, item) in enumerate(matches):
        item["step_order"] = idx + 1
        discovered_inputs.append(item)

    if action == "get" or not updates:
        return _envelope(
            True,
            f"discovered {len(discovered_inputs)} input(s) in {target_file.name}",
            data={
                "case_id": case_id,
                "file": str(target_file),
                "inputs": discovered_inputs,
            },
            artifacts=[str(target_file)],
        )

    updated_count = 0
    new_source = source
    inputs_by_sel = {str(inp.get("selector", "")): inp for inp in discovered_inputs}
    for upd in updates:
        target_input = _find_target_input(upd, discovered_inputs, inputs_by_sel)
        if not target_input:
            continue

        loc = target_input["selector"]
        escaped_loc = re.escape(loc)

        if "input_value" in upd and upd["input_value"] is not None:
            new_val = str(upd["input_value"])
            clean_val = new_val.replace("\\", "\\\\").replace('"', '\\"')
            if target_input["type"] in ("text", "password", "solve_captcha"):
                pattern = rf"await\s+{escaped_loc}\.fill\((.*?)\)"
                replacement = f'await {loc}.fill("{clean_val}")'
                new_source, n_sub = re.subn(pattern, replacement, new_source, count=1)
                if n_sub > 0:
                    updated_count += 1
            elif target_input["type"] == "select":
                pattern = rf"await\s+{escaped_loc}\.select_option\((.*?)\)"
                replacement = f'await {loc}.select_option("{clean_val}")'
                new_source, n_sub = re.subn(pattern, replacement, new_source, count=1)
                if n_sub > 0:
                    updated_count += 1

        if "file_paths" in upd and upd["file_paths"] is not None:
            new_files = upd["file_paths"]
            if isinstance(new_files, list):
                files_repr = json.dumps(new_files)
            else:
                files_repr = (
                    json.dumps([str(new_files)])
                    if target_input.get("is_multiple")
                    else json.dumps(str(new_files))
                )

            if upload_files_var_re.search(new_source):
                new_source, n_sub = upload_files_var_re.subn(
                    f"upload_files = {files_repr}", new_source, count=1
                )
                if n_sub > 0:
                    updated_count += 1
            else:
                pattern = rf"await\s+{escaped_loc}\.set_input_files\((.*?)\)"
                replacement = f"await {loc}.set_input_files({files_repr})"
                new_source, n_sub = re.subn(pattern, replacement, new_source, count=1)
                if n_sub > 0:
                    updated_count += 1

    if updated_count > 0:
        target_file.write_text(new_source, encoding="utf-8")
        api_url = os.environ.get("SUITEST_API_URL")
        api_key = os.environ.get("SUITEST_API_KEY")
        if api_url and api_key:
            with suppress(Exception):
                from suitest_lifecycle.blackbox.mcp import extract_steps_from_automation_code
                from suitest_lifecycle.http_client import SuitestClient

                with SuitestClient(api_url, token=api_key) as client:
                    api_steps = extract_steps_from_automation_code(new_source)
                    client.patch(f"/api/v1/test-cases/{case_id}/steps", json={"steps": api_steps})

    return _envelope(
        True,
        f"updated {updated_count} input(s) in {target_file.name}",
        data={
            "case_id": case_id,
            "file": str(target_file),
            "updated_count": updated_count,
        },
        artifacts=[str(target_file)],
    )


def manage_test_case_dataset(
    config_path: str = "suitest.config.json",
    case_id: str = "",
    action: str = "get",
    schema: list[str] | None = None,
    rows: list[dict[str, Any]] | None = None,
    old_column: str = "",
    new_column: str = "",
    output_dir: str = "",
    **kwargs: Any,
) -> dict[str, object]:
    """Inspect or update Data-Driven Testing (DDT) dataset scenario matrices on a test case."""
    out_dir = Path(output_dir).resolve() if output_dir else Path("suitest-output").resolve()
    if config_path and not output_dir:
        try:
            cfg = load_config(config_path)
            out_dir = cfg.output_dir
        except (ConfigError, OSError, ValueError) as err:
            logger.debug("Could not read output_dir from config %s: %s", config_path, err)
    paths = build_paths(out_dir, Mode.FRONTEND)
    mode_dir = paths.mode_dir

    if not case_id:
        return _envelope(False, "case_id is required", errors=["missing case_id"])

    sidecar_path = mode_dir / f"{case_id}.dataset.json"
    current_data: dict[str, Any] = {"schema": [], "rows": []}
    if sidecar_path.is_file():
        with suppress(Exception):
            current_data = json.loads(sidecar_path.read_text(encoding="utf-8"))

    from suitest_lifecycle.http_client import SuitestClient

    api_url = os.environ.get("SUITEST_API_URL")
    api_key = os.environ.get("SUITEST_API_KEY")

    if action == "get":
        if (
            not current_data.get("schema")
            and api_url
            and api_key
            and (case_id.startswith("tc_") or len(case_id) >= 20)
        ):
            try:
                with SuitestClient(api_url, token=api_key) as client:
                    case_res = client.get(f"/api/v1/test-cases/{case_id}")
                    current_data = {
                        "schema": case_res.get("dataset_schema")
                        or case_res.get("datasetSchema")
                        or [],
                        "rows": case_res.get("dataset_rows") or case_res.get("datasetRows") or [],
                    }
            except Exception as err:
                logger.debug("Could not retrieve remote dataset for %s: %s", case_id, err)
        return _envelope(
            True,
            f"dataset for {case_id}: {len(current_data.get('schema', []))} columns, {len(current_data.get('rows', []))} rows",
            data={
                "case_id": case_id,
                "dataset_schema": current_data.get("schema", []),
                "dataset_rows": current_data.get("rows", []),
            },
            artifacts=[str(sidecar_path)] if sidecar_path.is_file() else [],
        )

    if action == "rename_column":
        old_col = old_column.strip()
        new_col = new_column.strip()
        if not old_col or not new_col:
            return _envelope(False, "old_column and new_column are required for rename_column")
        cols = list(current_data.get("schema", []))
        if old_col not in cols:
            return _envelope(False, f"column '{old_col}' does not exist in dataset schema")
        if new_col in cols and new_col != old_col:
            return _envelope(False, f"column '{new_col}' already exists in dataset schema")

        new_cols = [new_col if c == old_col else c for c in cols]
        new_rows = []
        for r in current_data.get("rows", []):
            vals = dict(r.get("values", {}))
            if old_col in vals:
                vals[new_col] = vals.pop(old_col)
            row_copy = dict(r)
            row_copy["values"] = vals
            new_rows.append(row_copy)

        current_data = {"schema": new_cols, "rows": new_rows}
        mode_dir.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps(current_data, indent=2), encoding="utf-8")

        if api_url and api_key and (case_id.startswith("tc_") or len(case_id) >= 20):
            try:
                with SuitestClient(api_url, token=api_key) as client:
                    client.patch(
                        f"/api/v1/test-cases/{case_id}",
                        json={"dataset_schema": new_cols, "dataset_rows": new_rows},
                    )
            except Exception as err:
                logger.debug("Could not patch remote dataset schema for %s: %s", case_id, err)
        return _envelope(
            True,
            f"renamed column '{old_col}' to '{new_col}' in {case_id} dataset",
            data={
                "case_id": case_id,
                "dataset_schema": new_cols,
                "dataset_rows": new_rows,
            },
            artifacts=[str(sidecar_path)],
        )

    if action == "set":
        cols = list(schema) if schema is not None else current_data.get("schema", [])
        matrix_rows = list(rows) if rows is not None else current_data.get("rows", [])
        current_data = {"schema": cols, "rows": matrix_rows}
        mode_dir.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps(current_data, indent=2), encoding="utf-8")

        if api_url and api_key and (case_id.startswith("tc_") or len(case_id) >= 20):
            try:
                with SuitestClient(api_url, token=api_key) as client:
                    client.patch(
                        f"/api/v1/test-cases/{case_id}",
                        json={"dataset_schema": cols, "dataset_rows": matrix_rows},
                    )
            except Exception as err:
                logger.debug("Could not patch remote dataset rows for %s: %s", case_id, err)
        return _envelope(
            True,
            f"saved dataset for {case_id}: {len(cols)} columns, {len(matrix_rows)} scenario rows",
            data={
                "case_id": case_id,
                "dataset_schema": cols,
                "dataset_rows": matrix_rows,
            },
            artifacts=[str(sidecar_path)],
        )

    return _envelope(False, f"unknown action: {action}")


def get_workspace_variables(
    workspace_id: str = "",
    config_path: str = "suitest.config.json",
    **kwargs: Any,
) -> dict[str, object]:
    """Retrieve workspace variables for parameterization and DDT."""
    from suitest_lifecycle.http_client import SuitestClient

    api_url = os.environ.get("SUITEST_API_URL")
    api_key = os.environ.get("SUITEST_API_KEY")
    if not api_url or not api_key:
        return _envelope(False, "SUITEST_API_URL / SUITEST_API_KEY required")
    try:
        with SuitestClient(api_url, token=api_key) as client:
            ws_id = workspace_id or client.workspace_id
            if not ws_id:
                with suppress(Exception):
                    whoami = client.get("/api/v1/api-keys/whoami")
                    if isinstance(whoami, dict) and whoami.get("workspace_id"):
                        ws_id = str(whoami["workspace_id"])
            ws_id = ws_id or "default"
            vars_res = client.get(f"/api/v1/workspaces/{ws_id}/variables")
            items = vars_res.get("items", []) if isinstance(vars_res, dict) else vars_res
            return _envelope(
                True, f"retrieved {len(items)} workspace variable(s)", data={"variables": items}
            )
    except Exception as exc:
        return _envelope(False, f"failed to fetch workspace variables: {exc}", errors=[str(exc)])


def set_workspace_variable(
    key: str = "",
    value: str = "",
    is_secret: bool = False,
    description: str = "",
    workspace_id: str = "",
    config_path: str = "suitest.config.json",
    **kwargs: Any,
) -> dict[str, object]:
    """Create or update a workspace variable via API (with AES-GCM encryption for secrets)."""
    from suitest_lifecycle.http_client import SuitestClient

    api_url = os.environ.get("SUITEST_API_URL")
    api_key = os.environ.get("SUITEST_API_KEY")
    if not api_url or not api_key:
        return _envelope(False, "SUITEST_API_URL / SUITEST_API_KEY required")
    trimmed_key = key.strip()
    if not trimmed_key:
        return _envelope(False, "variable key is required")
    try:
        with SuitestClient(api_url, token=api_key) as client:
            ws_id = workspace_id or client.workspace_id
            if not ws_id:
                with suppress(Exception):
                    whoami = client.get("/api/v1/api-keys/whoami")
                    if isinstance(whoami, dict) and whoami.get("workspace_id"):
                        ws_id = str(whoami["workspace_id"])
            ws_id = ws_id or "default"
            payload = {
                "key": trimmed_key,
                "value": value,
                "is_secret": is_secret,
                "description": description,
            }
            # Check if variable already exists to update via PATCH
            existing_var = None
            with suppress(Exception):
                existing_res = client.get(f"/api/v1/workspaces/{ws_id}/variables")
                items = (
                    existing_res.get("items", [])
                    if isinstance(existing_res, dict)
                    else existing_res
                )
                if isinstance(items, list):
                    existing_var = next((v for v in items if v.get("key") == trimmed_key), None)
            if existing_var and isinstance(existing_var, dict) and existing_var.get("id"):
                res = client.patch(
                    f"/api/v1/workspaces/{ws_id}/variables/{existing_var['id']}", json=payload
                )
            else:
                res = client.post(f"/api/v1/workspaces/{ws_id}/variables", json=payload)
            return _envelope(True, f"saved variable '{trimmed_key}'", data=res)
    except Exception as exc:
        return _envelope(False, f"failed to save variable: {exc}", errors=[str(exc)])


def list_suites(
    project_id: str = "",
    config_path: str = "suitest.config.json",
    **kwargs: Any,
) -> dict[str, object]:
    """List test suites in a project."""
    from suitest_lifecycle.http_client import SuitestClient

    api_url = os.environ.get("SUITEST_API_URL")
    api_key = os.environ.get("SUITEST_API_KEY")
    if not api_url or not api_key:
        return _envelope(False, "SUITEST_API_URL / SUITEST_API_KEY required")
    try:
        with SuitestClient(api_url, token=api_key) as client:
            suites = client.list_suites(project_id=project_id)
            return _envelope(True, f"retrieved {len(suites)} suite(s)", data={"suites": suites})
    except Exception as exc:
        return _envelope(False, f"failed to list suites: {exc}", errors=[str(exc)])


def list_test_cases(
    project_id: str = "",
    suite_id: str = "",
    config_path: str = "suitest.config.json",
    **kwargs: Any,
) -> dict[str, object]:
    """List test cases in a project or suite."""
    from suitest_lifecycle.http_client import SuitestClient

    api_url = os.environ.get("SUITEST_API_URL")
    api_key = os.environ.get("SUITEST_API_KEY")
    if not api_url or not api_key:
        return _envelope(False, "SUITEST_API_URL / SUITEST_API_KEY required")
    pid = (project_id or "").strip()
    sid = (suite_id or "").strip()
    if (not pid and not sid) or (pid and sid):
        return _envelope(False, "pass exactly one of project_id or suite_id")
    try:
        with SuitestClient(api_url, token=api_key) as client:
            cases = client.list_cases(project_id=pid, suite_id=sid)
            return _envelope(
                True, f"retrieved {len(cases)} test case(s)", data={"test_cases": cases}
            )
    except Exception as exc:
        return _envelope(False, f"failed to list test cases: {exc}", errors=[str(exc)])


def get_test_case(
    case_id: str = "",
    config_path: str = "suitest.config.json",
    **kwargs: Any,
) -> dict[str, object]:
    """Retrieve test case details and steps by ID or public ID."""
    from suitest_lifecycle.http_client import SuitestClient

    api_url = os.environ.get("SUITEST_API_URL")
    api_key = os.environ.get("SUITEST_API_KEY")
    if not api_url or not api_key:
        return _envelope(False, "SUITEST_API_URL / SUITEST_API_KEY required")
    cid = (case_id or "").strip()
    if not cid:
        return _envelope(False, "case_id is required")
    try:
        with SuitestClient(api_url, token=api_key) as client:
            case_data = client.get_case(cid)
            return _envelope(True, f"retrieved test case {cid}", data=case_data)
    except Exception as exc:
        return _envelope(False, f"failed to get test case: {exc}", errors=[str(exc)])


def _resolve_suite_and_project(
    client: Any,
    project_id: str = "",
    suite_id: str = "",
    target_url: str = "",
) -> tuple[str, str]:
    """Resolve or auto-create project_id and suite_id if missing, guarding against empty query params."""
    p_id = project_id.strip()
    s_id = suite_id.strip()

    if not p_id:
        host = (target_url or "general-web").split("//")[-1].split("/")[0].removeprefix("www.")
        slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")[:64] or "general-web"
        proj = client.resolve_project(project_slug=slug, project_name=host or "General Web")
        p_id = str(proj.get("id") or "") if isinstance(proj, dict) else ""
    if not p_id:
        return "", ""

    if not s_id:
        existing_suites = client.list_suites(project_id=p_id)
        if (
            existing_suites
            and isinstance(existing_suites, list)
            and isinstance(existing_suites[0], dict)
        ):
            s_id = str(existing_suites[0].get("id") or "")
        else:
            if hasattr(client, "create_suite"):
                new_suite = client.create_suite(project_id=p_id, name="General Discovered Suite")
            else:
                new_suite = client.post(
                    "/api/v1/suites",
                    json_body={"projectId": p_id, "name": "General Discovered Suite"},
                )
            s_id = str(new_suite.get("id") or "") if isinstance(new_suite, dict) else ""

    return p_id, s_id


_PROVEN_TOGGLE_RE = re.compile(
    r"(?:"
    r"accordion|"
    r"collapse|"
    r"toggle|"
    r"\[aria-expanded|"
    r"\[aria-haspopup|"
    r"\[data-(?:bs-)?toggle|"
    r"\[data-(?:bs-)?target|"
    r"\[data-ktwizard-type|"
    r"\[data-state=[\"'](?:open|closed)[\"']|"
    r"kt-menu__toggle|"
    r"\bsummary\b|"
    r"\bdetails\b|"
    r"\[role=[\"'](?:tab|switch|checkbox|menuitemcheckbox)[\"']|"
    r"input\[type=[\"']checkbox[\"']"
    r")",
    re.IGNORECASE,
)


def _is_proven_redundant_toggle(target: str) -> bool:
    """Return True only if the target is a proven collapsible/accordion/toggle control."""
    if not target:
        return False
    return bool(_PROVEN_TOGGLE_RE.search(target))


def _prune_redundant_step_toggles(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prune immediate back-to-back clicks on identical targets that cause toggle re-collapse."""
    cleaned: list[dict[str, Any]] = []
    prev_tool = ""
    prev_target = ""

    for s in steps:
        cd = s.get("code")
        parsed: dict[str, Any] = {}
        if isinstance(cd, dict):
            parsed = cd
        elif isinstance(cd, str) and cd.strip():
            try:
                loaded = json.loads(cd)
                if isinstance(loaded, dict):
                    parsed = loaded
            except Exception:
                parsed = {}

        t = str(parsed.get("tool") or "")
        args = parsed.get("arguments")
        args_dict = args if isinstance(args, dict) else {}
        target = str(args_dict.get("target") or args_dict.get("selector") or "").strip()
        if (
            t in ("browser_click", "browser.click")
            and prev_tool in ("browser_click", "browser.click")
            and target
            and target == prev_target
            and _is_proven_redundant_toggle(target)
        ):
            # Skip consecutive duplicate click that re-collapses state on a proven toggle,
            # and reset tracker to prevent trailing absorption of subsequent clicks
            prev_tool = ""
            prev_target = ""
            continue

        cleaned.append(s)
        prev_tool = t or ""
        prev_target = target

    for idx, s in enumerate(cleaned, start=1):
        if "order" in s and isinstance(s["order"], int):
            s["order"] = idx

    return cleaned


def _extract_step_target_url(steps: list[dict[str, Any]]) -> str:
    """Extract navigation URL from steps if available."""
    for s in steps:
        cd = s.get("code")
        if isinstance(cd, str):
            try:
                cd = json.loads(cd)
            except Exception:
                cd = {}
        if isinstance(cd, dict) and cd.get("tool") in ("browser_navigate", "browser.navigate"):
            cand = str((cd.get("arguments") or {}).get("url") or "")
            if cand.startswith(("http://", "https://")):
                return cand
    return ""


def _render_step_code_line(tool: str, args: dict[str, Any]) -> str:
    """Render a single step Playwright Python action line."""
    if tool in ("browser_navigate", "browser.navigate"):
        return f'    await page.goto({args.get("url", "")!r}, wait_until="domcontentloaded")'
    if tool in ("browser_type", "browser.type"):
        tgt = args.get("target") or args.get("selector") or ""
        txt = args.get("text", "")
        if _is_sensitive_input(tgt, value=txt) and not (
            isinstance(txt, str) and txt.startswith("{{") and txt.endswith("}}")
        ):
            t_low = str(tgt).lower()
            var_name = "password" if ("pass" in t_low or "pwd" in t_low) else "secret"
            txt = f"{{{{{var_name}}}}}"
        return f"    await page.locator({tgt!r}).fill({txt!r})"
    if tool in ("browser_click", "browser.click"):
        tgt = args.get("target") or args.get("selector") or ""
        return f"    await page.locator({tgt!r}).click()"
    if tool in ("browser_solve_captcha", "browser.solve_captcha"):
        img_s = args.get("image_selector", "#img-captcha")
        inp_s = args.get("input_selector", "#captcha")
        return (
            f"    await _bb_solve_captcha(page, image_selector={img_s!r}, input_selector={inp_s!r})"
        )
    if tool in (
        "browser_select",
        "browser.select",
        "browser_select_option",
        "browser.select_option",
    ):
        tgt = args.get("target") or args.get("selector") or ""
        raw_val = args.get("value") or (
            args.get("values", [""])[0] if isinstance(args.get("values"), list) else ""
        )
        return f"    await page.locator({tgt!r}).select_option({str(raw_val)!r})"
    if tool in ("browser_upload_file", "browser.upload_file", "browser_file_upload"):
        tgt = args.get("target") or args.get("selector") or ""
        f_path = (
            args.get("file")
            or args.get("path")
            or (args.get("files", [""])[0] if isinstance(args.get("files"), list) else "")
        )
        return f"    await page.locator({tgt!r}).set_input_files({str(f_path)!r})"
    return ""


def _write_python_mirror_file(
    out_dir_path: Path,
    trimmed_name: str,
    description: str,
    case_steps: list[dict[str, Any]],
) -> Path | None:
    """Write local Python Playwright test mirror file."""
    try:
        out_dir_path.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", trimmed_name.lower()).strip("_")
        created_file = out_dir_path / f"TC_{slug}.py"
        step_body_lines: list[str] = []
        for idx, s in enumerate(case_steps, start=1):
            act = s.get("action", f"Step {idx}")
            cd = s.get("code") or "{}"
            step_body_lines.append(f'    _begin("action", {act!r})')
            try:
                parsed_c = json.loads(cd) if isinstance(cd, str) else cd
                t = str(parsed_c.get("tool") or "") if isinstance(parsed_c, dict) else ""
                args = parsed_c.get("arguments", {}) if isinstance(parsed_c, dict) else {}
                code_line = _render_step_code_line(t, args)
                if code_line:
                    step_body_lines.append(code_line)
            except (json.JSONDecodeError, TypeError, KeyError) as parse_err:
                logger.debug("create_test_case.step_code_parse_failed: %s", parse_err)
            step_body_lines.append("    await _ok(page)")

        helper_defs = (
            "def _begin(step_type, description):\n"
            "    pass\n\n"
            "async def _ok(page):\n"
            "    pass\n\n"
            "async def _bb_solve_captcha(page, image_selector='#img-captcha', input_selector='#captcha'):\n"
            "    pass\n\n"
        )
        py_content = (
            f"# {trimmed_name}\n"
            f"# Description: {description or 'None'}\n"
            "import os, pytest\n"
            "from playwright.async_api import async_playwright, expect\n\n"
            + helper_defs
            + "async def _body(page):\n"
            + ("\n".join(step_body_lines) if step_body_lines else "    pass\n")
        )
        created_file.write_text(py_content, encoding="utf-8")
        return created_file
    except Exception as exc:
        logger.debug("create_test_case.file_write_failed: %s", exc)
        return None


def _normalize_steps_for_tcm(case_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format and normalize case steps for the TCM API payload."""
    formatted_steps = []
    for idx, s in enumerate(case_steps):
        cd = s.get("code")
        if isinstance(cd, dict):
            tool_name = cd.get("tool", "")
            if tool_name in ("browser_select", "browser.select", "browser.select_option"):
                cd["tool"] = "browser_select_option"
                c_args = cd.setdefault("arguments", {})
                if "value" in c_args and "values" not in c_args:
                    val = c_args.pop("value")
                    c_args["values"] = (
                        [str(val)] if not isinstance(val, list) else list(map(str, val))
                    )
                if "selector" in c_args and "target" not in c_args:
                    c_args["target"] = c_args.pop("selector")
            elif tool_name in (
                "browser_upload_file",
                "browser.upload_file",
                "browser_file_upload",
            ):
                cd["tool"] = "browser_upload_file"
                c_args = cd.setdefault("arguments", {})
                if "path" in c_args and "file" not in c_args:
                    c_args["file"] = c_args.pop("path")
                if "selector" in c_args and "target" not in c_args:
                    c_args["target"] = c_args.pop("selector")
            elif tool_name in ("browser_type", "browser.type"):
                c_args = cd.setdefault("arguments", {})
                tgt = c_args.get("target") or c_args.get("selector") or ""
                txt = c_args.get("text", "")
                if _is_sensitive_input(tgt, value=txt) and not (
                    isinstance(txt, str) and txt.startswith("{{") and txt.endswith("}}")
                ):
                    t_low = str(tgt).lower()
                    var_name = "password" if ("pass" in t_low or "pwd" in t_low) else "secret"
                    c_args["text"] = f"{{{{{var_name}}}}}"
        formatted_steps.append(
            {
                "action": s.get("action", f"Step {idx + 1}"),
                "expected": s.get("expected", ""),
                "code": json.dumps(cd) if isinstance(cd, dict) else (cd or "{}"),
                "mcp_provider": s.get("mcp_provider") or s.get("mcpProvider") or "playwright-mcp",
                "target_kind": s.get("target_kind") or s.get("targetKind") or "FE_WEB",
                "order": s.get("order", idx),
            }
        )
    return formatted_steps


def create_test_case(
    suite_id: str = "",
    name: str = "",
    description: str = "",
    preconditions: str = "",
    priority: str = "P2",
    steps: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
    output_dir: str = "",
    config_path: str = "suitest.config.json",
    **kwargs: Any,
) -> dict[str, object]:
    """Create a new test case with steps, maintaining local file mirror and syncing to TCM."""
    from suitest_lifecycle.http_client import SuitestClient

    api_url = os.environ.get("SUITEST_API_URL")
    api_key = os.environ.get("SUITEST_API_KEY")
    if not api_url or not api_key:
        return _envelope(False, "SUITEST_API_URL / SUITEST_API_KEY required")
    trimmed_name = (name or "").strip()
    if not trimmed_name:
        return _envelope(False, "name is required")
    target_url = str(kwargs.get("target_url") or "") or _extract_step_target_url(steps or [])
    project_id = str(kwargs.get("project_id") or "")
    resolved_suite_id = (suite_id or "").strip()

    case_steps = _prune_redundant_step_toggles(steps or [])
    out_dir_path = Path(output_dir or "suitest-output/frontend").resolve()
    created_file = _write_python_mirror_file(out_dir_path, trimmed_name, description, case_steps)

    try:
        with SuitestClient(api_url, token=api_key) as client:
            if not resolved_suite_id:
                _, resolved_suite_id = _resolve_suite_and_project(
                    client, project_id=project_id, suite_id="", target_url=target_url
                )
                if not resolved_suite_id:
                    return _envelope(False, "unable to resolve or create suite_id")

            formatted_steps = _normalize_steps_for_tcm(case_steps)
            payload: dict[str, Any] = {
                "suiteId": resolved_suite_id,
                "name": trimmed_name,
                "description": description or None,
                "preconditions": preconditions or None,
                "priority": priority.upper() if priority else "P2",
                "steps": formatted_steps,
                "tags": tags or [],
            }
            res = client.create_case(payload)
            public_id = (
                (res.get("public_id") or res.get("publicId") or res.get("id") or "TC")
                if isinstance(res, dict)
                else "TC"
            )
            artifacts = [str(created_file)] if created_file and created_file.exists() else []
            return _envelope(
                True,
                f"created test case {public_id}: '{trimmed_name}' ({len(formatted_steps)} steps)",
                data=res,
                artifacts=artifacts,
            )
    except Exception as exc:
        return _envelope(False, f"failed to create test case: {exc}", errors=[str(exc)])


def run_test_case(
    case_id: str = "",
    config_path: str = "suitest.config.json",
    **kwargs: Any,
) -> dict[str, object]:
    """Trigger an immediate ad-hoc test run for a test case."""
    from suitest_lifecycle.http_client import SuitestClient

    api_url = os.environ.get("SUITEST_API_URL")
    api_key = os.environ.get("SUITEST_API_KEY")
    if not api_url or not api_key:
        return _envelope(False, "SUITEST_API_URL / SUITEST_API_KEY required")
    cid = (case_id or "").strip()
    if not cid:
        return _envelope(False, "case_id is required")
    try:
        with SuitestClient(api_url, token=api_key) as client:
            res = client.run_case(cid)
            run_public_id = res.get("publicId") or res.get("id") or "R"
            return _envelope(True, f"triggered run {run_public_id} for case {cid}", data=res)
    except Exception as exc:
        return _envelope(False, f"failed to run test case: {exc}", errors=[str(exc)])


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
    "whitebox_discover_tests": whitebox_discover_tests,
    "whitebox_run_tests": whitebox_run_tests,
    "edit_test_case_inputs": edit_test_case_inputs,
    "manage_test_case_dataset": manage_test_case_dataset,
    "get_workspace_variables": get_workspace_variables,
    "set_workspace_variable": set_workspace_variable,
    "list_suites": list_suites,
    "list_test_cases": list_test_cases,
    "get_test_case": get_test_case,
    "create_test_case": create_test_case,
    "run_test_case": run_test_case,
    "suitest_create_dummy_file": suitest_create_dummy_file,
    **BLACKBOX_TOOLS,
    **INTERACTIVE_BROWSER_TOOLS,
}

# Tools that take structured kwargs (url/username/case_id/…), not just config_path.
KWARG_TOOLS = frozenset(
    {
        *BLACKBOX_TOOLS,
        *INTERACTIVE_BROWSER_TOOLS,
        "suitest_create_dummy_file",
        "edit_test_case_inputs",
        "manage_test_case_dataset",
        "get_workspace_variables",
        "set_workspace_variable",
        "list_suites",
        "list_test_cases",
        "get_test_case",
        "create_test_case",
        "run_test_case",
    }
)

__all__ = ["KWARG_TOOLS", "TOOLS", *TOOLS.keys()]
