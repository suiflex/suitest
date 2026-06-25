"""Reporter plugin layer (M9-2).

Defines the :class:`ReporterBase` Protocol and stub implementations for
XRay and qTest.  Real implementations would POST to the vendor REST API;
these stubs log the call and return a mock success result so the plugin
contract is established without external dependencies.

Usage::

    from suitest_api.services.reporter_registry import reporter_registry

    reporter = reporter_registry.get("xray")
    result = await reporter.report_run_result(
        run_id="...",
        project_key="MY",
        results=[...],
        config={"base_url": "https://...", "token": "..."},
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import structlog

log = structlog.get_logger(__name__)


@dataclass
class RunStepResult:
    """Minimal result record passed to a reporter for one test-case step."""

    step_id: str
    test_case_id: str
    outcome: str  # "PASS" | "FAIL" | "SKIP" | "ERROR"
    duration_ms: int | None = None
    error_message: str | None = None


@dataclass
class ReportSubmissionResult:
    """Outcome of submitting a run report to an external system."""

    success: bool
    external_id: str | None = None
    url: str | None = None
    error: str | None = None


@runtime_checkable
class ReporterBase(Protocol):
    """Protocol every reporter plugin must satisfy.

    Reporters are stateless: all per-call context (credentials, project key,
    etc.) arrives via ``config``.  The registry holds a single shared instance
    per reporter name.
    """

    name: str

    async def report_run_result(
        self,
        run_id: str,
        project_key: str,
        results: list[RunStepResult],
        config: dict[str, str],
    ) -> ReportSubmissionResult:
        """Submit run results to the external test-management system.

        :param run_id: Suitest run ID.
        :param project_key: Target project key in the external system.
        :param results: Step-level results to report.
        :param config: Reporter-specific config (base_url, token, etc.).
        :returns: Submission outcome.
        """
        ...


class XRayReporter:
    """Stub XRay reporter (M9-2).

    Production implementation would POST to the Xray REST API
    ``/rest/raven/1.0/import/execution`` (Jira-Server) or
    ``/api/v2/import/execution`` (Xray Cloud).
    """

    name = "xray"

    async def report_run_result(
        self,
        run_id: str,
        project_key: str,
        results: list[RunStepResult],
        config: dict[str, str],
    ) -> ReportSubmissionResult:
        log.info(
            "reporter.xray.report_run_result",
            run_id=run_id,
            project_key=project_key,
            step_count=len(results),
            stub=True,
        )
        # Stub: simulate a successful XRay test execution import.
        return ReportSubmissionResult(
            success=True,
            external_id=f"XRAY-EXEC-{run_id[:8]}",
            url=config.get("base_url", "https://xray.example.com")
            + f"/rest/raven/1.0/import/execution/{run_id[:8]}",
        )


class QTestReporter:
    """Stub qTest reporter (M9-2).

    Production implementation would POST to the qTest Manager API
    ``/api/v3/projects/{projectId}/test-runs``.
    """

    name = "qtest"

    async def report_run_result(
        self,
        run_id: str,
        project_key: str,
        results: list[RunStepResult],
        config: dict[str, str],
    ) -> ReportSubmissionResult:
        log.info(
            "reporter.qtest.report_run_result",
            run_id=run_id,
            project_key=project_key,
            step_count=len(results),
            stub=True,
        )
        # Stub: simulate a successful qTest test run creation.
        return ReportSubmissionResult(
            success=True,
            external_id=f"QT-RUN-{run_id[:8]}",
            url=config.get("base_url", "https://qtest.example.com")
            + f"/p/{project_key}/portal#tab=testRun&object={run_id[:8]}",
        )
