"""Hermetic unit tests for Phase 2 lifecycle pieces (no external project, no network).

Covers: LLM enrichment determinism/idempotency, publish payload shaping, publish
graceful degrade, and runner sidecar/step collection. Run:

    PYTHONPATH=src python -m pytest tests/test_phase2.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

from suitest_lifecycle import publish
from suitest_lifecycle.config import Config
from suitest_lifecycle.enrich import MockLlmClient, enrich_plan
from suitest_lifecycle.models import (
    CodeSummary,
    Endpoint,
    Mode,
    PlanCase,
    PlanStep,
    Priority,
    RunSummary,
    StepResult,
    TestOutcome,
    TestResult,
)
from suitest_lifecycle.paths import build_paths
from suitest_lifecycle.runner import _collect_steps


def _summary() -> CodeSummary:
    return CodeSummary(
        project_name="demo",
        mode=Mode.BACKEND,
        endpoints=[
            Endpoint("POST", "/api/products", True, "src/products.ts"),
            Endpoint("GET", "/api/health", False, "src/app.ts"),
        ],
    )


def _cases() -> list[PlanCase]:
    return [
        PlanCase(
            id="TC001",
            title="post_api_products_with_valid_data_creates_resource",
            description="create",
            category="Products",
            priority=Priority.HIGH,
            steps=[PlanStep("action", "create")],
            source_ref="POST /api/products",
        )
    ]


# --- enrichment -------------------------------------------------------------
def test_enrich_baseline_identical_without_client() -> None:
    cases = _cases()
    assert enrich_plan(_summary(), cases, _config(), None) is cases


def test_enrich_mock_adds_traceable_llm_case() -> None:
    out = enrich_plan(_summary(), _cases(), _config(enrich=True), MockLlmClient())
    llm = [c for c in out if "llm" in c.tags]
    assert len(llm) == 1
    assert llm[0].source_ref == "POST /api/products"  # traceable, no dummy test
    assert llm[0].id == "TC002"


def test_enrich_is_idempotent() -> None:
    client = MockLlmClient()
    once = enrich_plan(_summary(), _cases(), _config(enrich=True), client)
    twice = enrich_plan(_summary(), once, _config(enrich=True), client)
    assert [c.title for c in once] == [c.title for c in twice]


# --- publish ----------------------------------------------------------------
def test_publish_case_payload_shape(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, Mode.BACKEND)
    paths.ensure()
    cases = _cases()
    cases[0].automation_file = "TC001.py"
    paths.test_file("TC001.py").write_text("import requests\n", encoding="utf-8")
    payloads = publish._case_payloads(cases, paths)
    assert payloads[0]["sourceRef"] == "POST /api/products"
    assert payloads[0]["automationCode"] == "import requests\n"
    assert payloads[0]["priority"] == "P1"
    # Title/slug split: slug keeps the technical key, title is humanized, and
    # name stays the slug (server-side idempotency match for legacy rows).
    assert payloads[0]["slug"] == "post_api_products_with_valid_data_creates_resource"
    assert payloads[0]["name"] == payloads[0]["slug"]
    assert payloads[0]["title"] == "Post API products with valid data creates resource"


def test_publish_scrubs_credentials_from_legacy_generated_code(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, Mode.FRONTEND)
    paths.ensure()
    cases = _cases()
    cases[0].automation_file = "TC001.py"
    paths.test_file("TC001.py").write_text(
        'USERNAME = "real-user@example.com"\nPASSWORD = "super-secret"\n',
        encoding="utf-8",
    )
    code = str(publish._case_payloads(cases, paths)[0]["automationCode"])
    assert "real-user@example.com" not in code
    assert "super-secret" not in code
    assert "SUITEST_TEST_USERNAME" in code and "SUITEST_TEST_PASSWORD" in code


def test_publish_result_payload_shape() -> None:
    cases = _cases()
    run = RunSummary(
        project="demo",
        mode=Mode.BACKEND,
        base_url="http://x",
        total=1,
        passed=1,
        failed=0,
        skipped=0,
        errored=0,
        duration_ms=5,
        results=[
            TestResult(
                test_id="TC001",
                title="t",
                description="",
                status=TestOutcome.PASSED,
                duration_ms=5,
                steps=[StepResult(1, "action", "do", TestOutcome.PASSED)],
            )
        ],
    )

    class _NoopUploader:
        def upload_file(self, path: str, *, content_type: str | None = None) -> str:
            raise AssertionError("no artifacts should upload in this test")

    payloads = publish._result_payloads(_NoopUploader(), run, cases)
    assert payloads[0]["sourceRef"] == "POST /api/products"
    assert payloads[0]["outcome"] == "PASSED"
    assert payloads[0]["steps"][0]["outcome"] == "PASSED"
    assert payloads[0]["slug"] == "post_api_products_with_valid_data_creates_resource"


def test_publish_disabled_returns_reason() -> None:
    res = publish.publish_results(_config(), _summary_run(), _cases(), _paths())
    assert res["published"] is False
    assert "disabled" in str(res["reason"])


def test_record_publish_surfaces_failure_in_errors() -> None:
    from suitest_lifecycle.orchestrator import _record_publish

    steps: list[str] = []
    errors: list[str] = []
    _record_publish({"published": False, "reason": "boom"}, steps, errors)
    assert errors == ["publish skipped — boom"]
    _record_publish({"published": True, "runId": "r1", "imported": 2}, steps, errors)
    assert len(steps) == 2 and len(errors) == 1  # success adds a step, no error


# --- runner step collection -------------------------------------------------
def test_collect_steps_reads_frontend_sidecar(tmp_path: Path) -> None:
    case = PlanCase(id="TC009", title="t", description="", category="x", priority=Priority.LOW)
    sidecar = tmp_path / "TC009.result.json"
    sidecar.write_text(
        json.dumps(
            {
                "steps": [{"index": 1, "type": "action", "description": "go", "status": "PASSED"}],
                "video": "/tmp/v.webm",
                "screenshot": "/tmp/s.png",
            }
        ),
        encoding="utf-8",
    )
    steps, video, shot = _collect_steps(case, tmp_path, TestOutcome.PASSED)
    assert len(steps) == 1 and steps[0].status is TestOutcome.PASSED
    assert video == "/tmp/v.webm" and shot == "/tmp/s.png"


def test_collect_steps_derives_backend_from_plan_on_fail(tmp_path: Path) -> None:
    case = PlanCase(
        id="TC001",
        title="t",
        description="",
        category="x",
        priority=Priority.LOW,
        steps=[PlanStep("action", "a"), PlanStep("assertion", "b")],
    )
    steps, _video, _shot = _collect_steps(case, tmp_path, TestOutcome.FAILED)
    assert [s.status for s in steps] == [TestOutcome.PASSED, TestOutcome.FAILED]


# --- helpers ----------------------------------------------------------------
def _config(*, enrich: bool = False) -> Config:
    return Config(
        mode=Mode.BACKEND,
        project_name="demo",
        project_path=Path("."),
        base_url="http://localhost:4000",
        enrich=enrich,
    )


def _paths():
    return build_paths(Path("/tmp/suitest-test-out"), Mode.BACKEND)


def _summary_run() -> RunSummary:
    return RunSummary(
        project="demo",
        mode=Mode.BACKEND,
        base_url="http://x",
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        errored=0,
        duration_ms=0,
    )
