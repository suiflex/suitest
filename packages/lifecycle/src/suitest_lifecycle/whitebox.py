"""Framework-neutral white-box contract with pytest and Vitest/Jest adapters."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING, Protocol

from suitest_lifecycle import pydeps
from suitest_lifecycle.models import (
    CodeSummary,
    PlanCase,
    PlanStep,
    Priority,
    RunSummary,
    StepResult,
    TestingApproach,
    TestOutcome,
    TestResult,
)
from suitest_lifecycle.paths import build_paths
from suitest_lifecycle.prd import build_prd
from suitest_lifecycle.report import write_all_reports
from suitest_lifecycle.serialize import (
    code_summary_to_json,
    plan_to_json,
    prd_to_json,
    results_to_json,
)
from suitest_lifecycle.strategy import apply_strategy
from suitest_lifecycle.tcm import sync_tcm

if TYPE_CHECKING:
    from pathlib import Path

    from suitest_lifecycle.config import Config
    from suitest_lifecycle.paths import Paths

WHITEBOX_CAPABILITY = "suitest.whitebox.v1"
_SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "suitest-output",
    "dist",
    "build",
}


@dataclass(frozen=True)
class WhiteboxDiscovery:
    capability: str
    framework: str
    command: list[str]
    targets: list[Path]
    coverage_file: Path | None

    def to_json(self, root: Path) -> dict[str, object]:
        return {
            "capability": self.capability,
            "framework": self.framework,
            "command": self.command,
            "targets": [str(path.relative_to(root)) for path in self.targets],
            "coverageFile": (
                str(self.coverage_file.relative_to(root)) if self.coverage_file else None
            ),
        }


class WhiteboxAdapter(Protocol):
    framework: str

    def discover(self, project_path: Path) -> WhiteboxDiscovery: ...

    def command_for(self, target: Path) -> list[str]: ...

    def ensure_runtime(self) -> pydeps.DepStatus: ...


def _walk(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    found: set[Path] = set()
    matches = chain.from_iterable(map(root.rglob, patterns))
    for path in matches:
        if path.is_file() and _allowed_path(path):
            found.add(path)
    ordered = list(found)
    ordered.sort()
    return ordered


def _allowed_path(path: Path) -> bool:
    return not any(part in _SKIP_DIRS for part in path.parts)


class PytestAdapter:
    framework = "pytest"

    def __init__(self, project_path: Path | None = None) -> None:
        # The project's tests import the project's dependencies, which Suitest's
        # own interpreter knows nothing about — so run them with the venv in the
        # repo when there is one. This mirrors NodeTestAdapter, which shells out
        # to `npm exec` and therefore already resolves the project's toolchain.
        self.python = pydeps.project_interpreter(project_path) if project_path else None

    @property
    def interpreter(self) -> str:
        return self.python or sys.executable

    def ensure_runtime(self) -> pydeps.DepStatus:
        """Provision pytest when falling back to Suitest's own interpreter.

        A project venv is assumed to carry its own pytest; installing into it
        would be Suitest mutating the user's environment uninvited.
        """
        if self.python is not None:
            return pydeps.DepStatus(True, f"project interpreter: {self.python}")
        return pydeps.ensure("pytest")

    def discover(self, project_path: Path) -> WhiteboxDiscovery:
        targets = _walk(project_path, ("test_*.py", "*_test.py"))
        coverage = project_path / "coverage.json"
        return WhiteboxDiscovery(
            capability=WHITEBOX_CAPABILITY,
            framework=self.framework,
            command=[self.interpreter, "-m", "pytest", "-q"],
            targets=targets,
            coverage_file=coverage,
        )

    def command_for(self, target: Path) -> list[str]:
        return [self.interpreter, "-m", "pytest", "-q", str(target)]


class NodeTestAdapter:
    def __init__(self, framework: str) -> None:
        self.framework = framework

    def ensure_runtime(self) -> pydeps.DepStatus:
        # `npm exec` already resolves the project's own node_modules.
        return pydeps.DepStatus(True, "project toolchain via npm exec")

    def discover(self, project_path: Path) -> WhiteboxDiscovery:
        targets = _walk(
            project_path,
            ("*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx", "*.test.js", "*.spec.js"),
        )
        coverage = project_path / "coverage" / "coverage-final.json"
        command = (
            ["npm", "exec", "--", "vitest", "run"]
            if self.framework == "vitest"
            else ["npm", "exec", "--", "jest", "--runInBand"]
        )
        return WhiteboxDiscovery(
            capability=WHITEBOX_CAPABILITY,
            framework=self.framework,
            command=command,
            targets=targets,
            coverage_file=coverage,
        )

    def command_for(self, target: Path) -> list[str]:
        if self.framework == "vitest":
            return ["npm", "exec", "--", "vitest", "run", str(target)]
        return ["npm", "exec", "--", "jest", str(target), "--runInBand"]


def detect_adapter(project_path: Path, requested: str = "") -> WhiteboxAdapter:
    normalized = requested.strip().lower()
    if normalized == "pytest" or (
        not normalized
        and ((project_path / "pyproject.toml").is_file() or (project_path / "pytest.ini").is_file())
    ):
        return PytestAdapter(project_path)
    package_json = project_path / "package.json"
    package_text = package_json.read_text(encoding="utf-8") if package_json.is_file() else ""
    if normalized in {"vitest", "jest"}:
        return NodeTestAdapter(normalized)
    if "vitest" in package_text:
        return NodeTestAdapter("vitest")
    if "jest" in package_text:
        return NodeTestAdapter("jest")
    raise ValueError(
        "no white-box adapter detected; set testing.framework to pytest, vitest, or jest"
    )


def discover(config: Config) -> WhiteboxDiscovery:
    adapter = detect_adapter(config.project_path, config.testing.framework)
    detected = adapter.discover(config.project_path)
    coverage = (
        (config.project_path / config.testing.coverage_file).resolve()
        if config.testing.coverage_file
        else detected.coverage_file
    )
    return WhiteboxDiscovery(
        capability=detected.capability,
        framework=detected.framework,
        command=config.testing.command or detected.command,
        targets=detected.targets,
        coverage_file=coverage,
    )


def _slug(path: Path) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in path.stem.lower())
    return "_".join(part for part in safe.split("_") if part) or "whitebox_test"


def _copy_target(target: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target, destination)


def _run_command(
    command: list[str], cwd: Path, timeout_sec: int = 300
) -> tuple[TestOutcome, int, str, str]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return TestOutcome.ERROR, int((time.monotonic() - started) * 1000), stdout, stderr
    outcome = TestOutcome.PASSED if result.returncode == 0 else TestOutcome.FAILED
    return outcome, int((time.monotonic() - started) * 1000), result.stdout, result.stderr


def _pct(covered: object, total: object) -> float:
    if not isinstance(covered, (int, float)) or not isinstance(total, (int, float)) or total == 0:
        return 0.0
    return round(float(covered) / float(total) * 100, 2)


def normalize_coverage(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    totals = raw.get("totals")
    if isinstance(totals, dict):
        lines_total = totals.get("num_statements", 0)
        lines_covered = totals.get("covered_lines", 0)
        branches_total = totals.get("num_branches", 0)
        branches_covered = totals.get("covered_branches", 0)
        return {
            "lines": {
                "total": lines_total,
                "covered": lines_covered,
                "percent": totals.get("percent_covered", _pct(lines_covered, lines_total)),
            },
            "branches": {
                "total": branches_total,
                "covered": branches_covered,
                "percent": _pct(branches_covered, branches_total),
            },
            "thresholdSource": "repository",
        }
    total = raw.get("total")
    if isinstance(total, dict):
        normalized: dict[str, object] = {"thresholdSource": "repository"}
        for key in ("lines", "branches", "functions", "statements"):
            value = total.get(key)
            if isinstance(value, dict):
                normalized[key] = {
                    "total": value.get("total", 0),
                    "covered": value.get("covered", 0),
                    "percent": value.get("pct", 0),
                }
        return normalized
    return {"raw": raw, "thresholdSource": "repository"}


def _cases(
    config: Config, discovery: WhiteboxDiscovery, paths: Paths
) -> tuple[list[PlanCase], list[Path]]:
    targets = discovery.targets
    if config.testing.command:
        command_file = paths.test_file("TC001_whitebox_command.txt")
        command_file.write_text(" ".join(config.testing.command) + "\n", encoding="utf-8")
        return (
            [
                PlanCase(
                    id="TC001",
                    title="configured_whitebox_suite",
                    description="Run the repository's configured white-box test command.",
                    category="White-box",
                    priority=Priority.HIGH,
                    steps=[
                        PlanStep(type="action", description="Execute configured test command"),
                        PlanStep(
                            type="assertion",
                            description="Framework exits successfully and coverage gates pass",
                        ),
                    ],
                    source_ref="repository:test-command",
                    automation_file=command_file.name,
                    testing_approach=TestingApproach.WHITE_BOX,
                    test_level=config.testing.level,
                    framework=discovery.framework,
                )
            ],
            [config.project_path],
        )
    cases: list[PlanCase] = []
    for index, target in enumerate(targets, start=1):
        test_id = f"TC{index:03d}"
        output_name = f"{test_id}_{_slug(target)}{target.suffix}"
        _copy_target(target, paths.test_file(output_name))
        cases.append(
            PlanCase(
                id=test_id,
                title=f"whitebox_{_slug(target)}",
                description=f"Run native {discovery.framework} tests from {target.name}.",
                category="White-box",
                priority=Priority.HIGH,
                steps=[
                    PlanStep(type="action", description=f"Execute {target.name}"),
                    PlanStep(
                        type="assertion",
                        description="Framework exits successfully and repository gates pass",
                    ),
                ],
                source_ref=f"repository:{target.relative_to(config.project_path)}",
                automation_file=output_name,
                testing_approach=TestingApproach.WHITE_BOX,
                test_level=config.testing.level,
                framework=discovery.framework,
            )
        )
    return cases, targets


def execute(config: Config) -> tuple[CodeSummary, list[PlanCase], RunSummary, Paths]:
    discovery = discover(config)
    paths = build_paths(config.output_dir, config.mode)
    paths.ensure()
    cases, targets = _cases(config, discovery, paths)
    summary = CodeSummary(
        project_name=config.project_name,
        mode=config.mode,
        tech_stack=[discovery.framework, "whitebox"],
        features=[str(path.relative_to(config.project_path)) for path in discovery.targets],
    )
    strategy = apply_strategy(config, summary, cases)
    for case in cases:
        case.testing_approach = TestingApproach.WHITE_BOX
        case.test_level = config.testing.level
        case.framework = discovery.framework
    results: list[TestResult] = []
    adapter = detect_adapter(config.project_path, discovery.framework)
    runtime = adapter.ensure_runtime()
    if not runtime.ready:
        raise RuntimeError(f"white-box runtime unavailable: {runtime.detail}")
    for case, target in zip(cases, targets, strict=True):
        command = config.testing.command or adapter.command_for(target)
        outcome, duration_ms, stdout, stderr = _run_command(command, config.project_path)
        error = stderr.strip() if outcome is not TestOutcome.PASSED else ""
        results.append(
            TestResult(
                test_id=case.id,
                title=case.title,
                description=case.description,
                status=outcome,
                duration_ms=duration_ms,
                error=error,
                automation_file=case.automation_file,
                stdout=stdout,
                stderr=stderr,
                steps=[
                    StepResult(
                        index=1,
                        type="action",
                        description=case.steps[0].description,
                        status=outcome,
                    ),
                    StepResult(
                        index=2,
                        type="assertion",
                        description=case.steps[1].description,
                        status=outcome,
                    ),
                ],
                testing_approach=TestingApproach.WHITE_BOX,
                test_level=config.testing.level,
                framework=discovery.framework,
            )
        )
    coverage = normalize_coverage(discovery.coverage_file)
    run = RunSummary(
        project=config.project_name,
        mode=config.mode,
        base_url=config.base_url,
        total=len(results),
        passed=sum(result.status is TestOutcome.PASSED for result in results),
        failed=sum(result.status is TestOutcome.FAILED for result in results),
        skipped=0,
        errored=sum(result.status is TestOutcome.ERROR for result in results),
        duration_ms=sum(result.duration_ms for result in results),
        results=results,
        ready=True,
        ready_detail=f"{discovery.framework} provider discovered {len(cases)} target(s)",
        coverage=coverage,
    )
    prd = build_prd(summary, datetime_today(), config.project_name)
    paths.code_summary_json.write_text(
        json.dumps(code_summary_to_json(summary), indent=2), encoding="utf-8"
    )
    paths.prd_json.write_text(json.dumps(prd_to_json(prd), indent=2), encoding="utf-8")
    paths.test_strategy_json.write_text(json.dumps(strategy, indent=2), encoding="utf-8")
    paths.test_plan_json.write_text(json.dumps(plan_to_json(cases), indent=2), encoding="utf-8")
    paths.test_results_json.write_text(
        json.dumps(results_to_json(results), indent=2), encoding="utf-8"
    )
    if coverage is not None:
        paths.coverage_json.write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    write_all_reports(run, paths, datetime_today())
    sync_tcm(cases, run, paths, config.mode, datetime_now())
    return summary, cases, run, paths


def datetime_today() -> str:
    import datetime

    return datetime.date.today().isoformat()


def datetime_now() -> str:
    import datetime

    return datetime.datetime.now().replace(microsecond=0).isoformat()


__all__ = [
    "WHITEBOX_CAPABILITY",
    "WhiteboxDiscovery",
    "detect_adapter",
    "discover",
    "execute",
    "normalize_coverage",
]
