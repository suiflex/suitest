"""Hermetic self-tests for retest hardening (no network, no real SDK).

Covers the MCP production-readiness acceptance scenarios:
binding valid/repaired/missing/first-setup/local-only/recreate, snapshot change
detection (UI/API/auth/schema), failure classification, generated-code
reuse/versioning/needs_review, and the publish decision matrix.

Run: PYTHONPATH=src python -m pytest tests/test_retest.py -q
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import ClassVar

import pytest
from suitest_lifecycle import retest as rt
from suitest_lifecycle.config import Config, PublishConfig
from suitest_lifecycle.models import (
    CodeSummary,
    Endpoint,
    Mode,
    Page,
    PlanCase,
    PlanStep,
    Priority,
    RunSummary,
    TestOutcome,
    TestResult,
)
from suitest_lifecycle.paths import build_paths
from suitest_lifecycle.publish import publish_results


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _config(
    tmp_path: Path,
    *,
    enabled: bool = True,
    project_id: str = "proj_live",
    recreate: bool = False,
    mode: Mode = Mode.BACKEND,
) -> Config:
    cfg_file = tmp_path / "suitest.config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "mode": mode.value,
                "projectName": "Demo App",
                "baseUrl": "http://localhost:3000",
                "publish": {"enabled": enabled, "projectId": project_id},
            }
        ),
        encoding="utf-8",
    )
    return Config(
        mode=mode,
        project_name="Demo App",
        project_path=tmp_path,
        base_url="http://localhost:3000",
        publish=PublishConfig(
            enabled=enabled,
            api_url="http://localhost:4000",
            project_id=project_id,
            recreate=recreate,
        ),
        output_dir=tmp_path / "suitest-output",
        config_path=cfg_file,
    )


class FakeBindingClient:
    def __init__(self, response: dict[str, object] | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []

    def resolve_project(
        self, *, project_id: str = "", project_slug: str = "", project_name: str = ""
    ) -> dict[str, object]:
        self.calls.append(
            {"project_id": project_id, "project_slug": project_slug, "project_name": project_name}
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _summary(mode: Mode = Mode.BACKEND) -> CodeSummary:
    return CodeSummary(
        project_name="Demo App",
        mode=mode,
        endpoints=[
            Endpoint(
                "POST",
                "/api/products",
                True,
                "src/products.ts",
                request_example={"name": "x", "price": 1},
            ),
            Endpoint("GET", "/api/health", False, "src/app.ts"),
        ],
        pages=[
            Page("/login", "LoginPage", False, "src/Login.tsx"),
            Page("/dashboard", "DashboardPage", True, "src/Dash.tsx"),
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
            steps=[PlanStep("action", "POST /api/products"), PlanStep("assertion", "201")],
            source_ref="POST /api/products",
            automation_file="TC001_create.py",
        )
    ]


def _run(results: list[TestResult]) -> RunSummary:
    failed = sum(1 for r in results if r.status is not TestOutcome.PASSED)
    return RunSummary(
        project="Demo App",
        mode=Mode.BACKEND,
        base_url="http://localhost:3000",
        total=len(results),
        passed=len(results) - failed,
        failed=failed,
        skipped=0,
        errored=0,
        duration_ms=10,
        results=results,
    )


# --------------------------------------------------------------------------- #
# 1. project binding — decision matrix
# --------------------------------------------------------------------------- #
def test_binding_publish_disabled_is_local_only(tmp_path: Path) -> None:
    cfg = _config(tmp_path, enabled=False)
    b = rt.resolve_binding(cfg, client=FakeBindingClient({"status": "valid"}))
    assert b.status == "local_only"
    assert not b.blocks_publish


def test_binding_no_project_id_is_first_setup(tmp_path: Path) -> None:
    cfg = _config(tmp_path, project_id="")
    b = rt.resolve_binding(cfg, client=FakeBindingClient({"status": "missing"}))
    assert b.status == "first_setup"
    assert "demo-app" in b.detail  # server will find-or-create by slug


def test_binding_valid_reuses_project(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    client = FakeBindingClient({"status": "valid", "projectId": "proj_live"})
    b = rt.resolve_binding(cfg, client=client)
    assert (b.status, b.action) == ("valid", "reused_existing_project")
    assert b.project_id == "proj_live"
    assert client.calls[0]["project_slug"] == "demo-app"


def test_binding_stale_id_auto_repairs_and_rewrites_config(tmp_path: Path) -> None:
    cfg = _config(tmp_path, project_id="proj_gone")
    b = rt.resolve_binding(
        cfg,
        client=FakeBindingClient(
            {"status": "repaired", "projectId": "proj_new", "matchedBy": "slug"}
        ),
    )
    assert b.status == "repaired"
    assert b.project_id == "proj_new"
    raw = json.loads(cfg.config_path.read_text())
    assert raw["publish"]["projectId"] == "proj_new"  # config file rewritten


def test_binding_stale_id_unrepairable_fails_and_never_recreates(tmp_path: Path) -> None:
    cfg = _config(tmp_path, project_id="proj_gone")
    b = rt.resolve_binding(cfg, client=FakeBindingClient({"status": "missing"}))
    assert b.status == "missing"
    assert b.blocks_publish
    assert "recreateProject" in b.detail  # clear next action in the message


def test_binding_recreate_only_with_explicit_flag(tmp_path: Path) -> None:
    cfg = _config(tmp_path, project_id="proj_gone")
    missing = FakeBindingClient({"status": "missing"})
    assert rt.resolve_binding(cfg, client=missing).status == "missing"
    b = rt.resolve_binding(cfg, recreate=True, client=FakeBindingClient({"status": "missing"}))
    assert b.status == "recreate_requested"
    assert not b.blocks_publish


def test_binding_server_unreachable_is_unverified_not_blocked(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    b = rt.resolve_binding(cfg, client=FakeBindingClient(ConnectionError("boom")))
    # Server-side _ensure_project still 404s a stale id without inserting, so
    # an unreachable resolve endpoint must not hard-block the run.
    assert b.status == "unverified"
    assert not b.blocks_publish


# --------------------------------------------------------------------------- #
# 2. snapshot change detection
# --------------------------------------------------------------------------- #
def test_snapshot_no_change_reports_clean(tmp_path: Path) -> None:
    fp = rt.build_fingerprint(_summary(), _cases())
    report = rt.diff_fingerprint(fp, fp)
    assert report == {
        "first": False,
        "changed": False,
        "uiChanged": False,
        "apiChanged": False,
        "breaking": False,
        "changes": [],
    }


def test_snapshot_first_run_flagged(tmp_path: Path) -> None:
    assert rt.diff_fingerprint(None, rt.build_fingerprint(_summary(), _cases()))["first"] is True


def _kinds(report: dict[str, object]) -> set[str]:
    return {c["kind"] for c in report["changes"]}  # type: ignore[index, union-attr]


def test_snapshot_endpoint_path_change_is_breaking(tmp_path: Path) -> None:
    prev = rt.build_fingerprint(_summary(), _cases())
    new = _summary()
    new.endpoints[0] = Endpoint(
        "POST",
        "/api/v2/products",
        True,
        "src/products.ts",
        request_example={"name": "x", "price": 1},
    )
    report = rt.diff_fingerprint(prev, rt.build_fingerprint(new, _cases()))
    assert {"endpoint_removed", "endpoint_added"} <= _kinds(report)
    assert report["apiChanged"] and report["breaking"]


def test_snapshot_request_schema_change_detected(tmp_path: Path) -> None:
    prev = rt.build_fingerprint(_summary(), _cases())
    new = _summary()
    new.endpoints[0] = Endpoint(
        "POST",
        "/api/products",
        True,
        "src/products.ts",
        request_example={"name": "x", "price": 1, "sku": "y"},
    )
    report = rt.diff_fingerprint(prev, rt.build_fingerprint(new, _cases()))
    assert _kinds(report) == {"request_schema_changed"}
    assert report["apiChanged"] and not report["breaking"]


def test_snapshot_auth_change_detected(tmp_path: Path) -> None:
    prev = rt.build_fingerprint(_summary(), _cases())
    new = _summary()
    new.endpoints[1] = Endpoint("GET", "/api/health", True, "src/app.ts")
    report = rt.diff_fingerprint(prev, rt.build_fingerprint(new, _cases()))
    assert _kinds(report) == {"auth_flow_changed"}
    assert report["breaking"]


def test_snapshot_route_change_is_ui_change(tmp_path: Path) -> None:
    prev = rt.build_fingerprint(_summary(), _cases())
    new = _summary()
    new.pages[1] = Page("/home", "DashboardPage", True, "src/Dash.tsx")
    report = rt.diff_fingerprint(prev, rt.build_fingerprint(new, _cases()))
    assert {"route_removed", "route_added"} <= _kinds(report)
    assert report["uiChanged"] and report["breaking"]


def test_snapshot_case_step_change_detected(tmp_path: Path) -> None:
    prev = rt.build_fingerprint(_summary(), _cases())
    changed = _cases()
    changed[0].steps.append(PlanStep("assertion", "response has sku"))
    report = rt.diff_fingerprint(prev, rt.build_fingerprint(_summary(), changed))
    assert _kinds(report) == {"case_steps_changed"}


def test_snapshot_persist_roundtrip(tmp_path: Path) -> None:
    paths = build_paths(tmp_path / "out", Mode.BACKEND)
    paths.ensure()
    fp = rt.build_fingerprint(_summary(), _cases())
    assert rt.load_snapshot(paths) is None
    rt.save_snapshot(paths, fp)
    assert rt.load_snapshot(paths) == fp


# --------------------------------------------------------------------------- #
# 3. failure classification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("error", "mode", "expected"),
    [
        ("TimeoutError: waiting for locator('#submit')", Mode.FRONTEND, "selector_changed"),
        ("strict mode violation: element not found", Mode.FRONTEND, "element_missing"),
        ("expect(page).to_have_url('/dashboard') failed", Mode.FRONTEND, "navigation_changed"),
        ("401 Unauthorized on login", Mode.FRONTEND, "auth_flow_changed"),
        ("HTTP 404 Not Found for /api/products", Mode.BACKEND, "endpoint_not_found"),
        ("405 Method Not Allowed", Mode.BACKEND, "method_mismatch"),
        ("AssertionError: expected 201 ... got 400", Mode.BACKEND, "status_code_changed"),
        ("KeyError: 'productId'", Mode.BACKEND, "response_schema_changed"),
        ("422 Unprocessable Entity: validation failed", Mode.BACKEND, "validation_error"),
        ("ConnectionError: ECONNREFUSED 127.0.0.1:4000", Mode.BACKEND, "backend_down"),
        ("500 Internal Server Error", Mode.BACKEND, "server_error"),
        ("Request timed out after 30000ms", Mode.BACKEND, "timeout"),
        ("", Mode.BACKEND, ""),
    ],
)
def test_classify_failure(error: str, mode: Mode, expected: str) -> None:
    assert rt.classify_failure(error, mode) == expected


def test_frontend_failure_with_api_change_is_integration_change() -> None:
    kind = rt.classify_failure(
        "KeyError: 'newField' in api response", Mode.FRONTEND, api_changed=True
    )
    assert kind == "frontend_backend_integration_changed"


def test_classify_results_maps_failed_only() -> None:
    results = [
        TestResult("TC001", "t", "", TestOutcome.PASSED, 1),
        TestResult("TC002", "t", "", TestOutcome.FAILED, 1, error="404 Not Found"),
    ]
    assert rt.classify_results(results, Mode.BACKEND) == {"TC002": "endpoint_not_found"}


# --------------------------------------------------------------------------- #
# 4. generated-code metadata: reuse / version / needs_review
# --------------------------------------------------------------------------- #
def test_codegen_new_then_unchanged_then_regenerated(tmp_path: Path) -> None:
    paths = build_paths(tmp_path / "out", Mode.BACKEND)
    paths.ensure()
    cases = _cases()
    f = paths.test_file(cases[0].automation_file)
    f.write_text("code v1", encoding="utf-8")

    meta1, c1 = rt.reconcile_codegen(cases, paths, {}, {}, "dom", "auto")
    assert c1 == {"new": 1, "regenerated": 0, "unchanged": 0, "reused": 0, "needs_review": 0}
    assert meta1[cases[0].title]["version"] == 1

    meta2, c2 = rt.reconcile_codegen(cases, paths, meta1, {}, "dom", "auto")
    assert c2["unchanged"] == 1 and meta2[cases[0].title]["version"] == 1

    stash = {cases[0].automation_file: "code v1"}
    f.write_text("code v2", encoding="utf-8")
    meta3, c3 = rt.reconcile_codegen(cases, paths, meta2, stash, "dom", "auto")
    assert c3["regenerated"] == 1 and meta3[cases[0].title]["version"] == 2
    history = paths.mode_dir / "history" / f"{cases[0].automation_file}.v1"
    assert history.read_text(encoding="utf-8") == "code v1"  # no silent overwrite


def test_codegen_reuse_when_inputs_unchanged(tmp_path: Path) -> None:
    paths = build_paths(tmp_path / "out", Mode.BACKEND)
    paths.ensure()
    cases = _cases()
    paths.test_file(cases[0].automation_file).write_text("code", encoding="utf-8")
    meta, _ = rt.reconcile_codegen(cases, paths, {}, {}, "dom", "auto")
    assert rt.can_reuse_generated(cases, paths, meta, "dom", "auto") is True
    assert rt.can_reuse_generated(cases, paths, meta, "OTHER_DOM", "auto") is False
    changed = _cases()
    changed[0].steps.append(PlanStep("assertion", "extra"))
    assert rt.can_reuse_generated(changed, paths, meta, "dom", "auto") is False


def test_codegen_export_failure_marks_needs_review(tmp_path: Path) -> None:
    paths = build_paths(tmp_path / "out", Mode.BACKEND)
    paths.ensure()
    cases = _cases()
    paths.test_file(cases[0].automation_file).write_text("old good code", encoding="utf-8")
    meta, _ = rt.reconcile_codegen(cases, paths, {}, {}, "dom", "auto")
    meta2, counts = rt.reconcile_codegen(
        cases, paths, meta, {}, "dom", "auto", export_error="LLM bridge 500"
    )
    assert counts["needs_review"] == 1
    assert meta2[cases[0].title]["status"] == "needs_review"
    assert meta2[cases[0].title]["error"] == "LLM bridge 500"


# --------------------------------------------------------------------------- #
# 5. publish decision matrix (fake SDK, no network)
# --------------------------------------------------------------------------- #
class _FakeSdkClient:
    last: _FakeSdkClient | None = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.bulk_kwargs: dict[str, object] = {}
        self.ingest_kwargs: dict[str, object] = {}
        _FakeSdkClient.last = self

    def __enter__(self) -> _FakeSdkClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def upload_file(self, path: str, *, content_type: str | None = None) -> str:
        return "s3://fake/" + path

    def bulk_import_cases(self, **kwargs: object) -> dict[str, object]:
        self.bulk_kwargs = kwargs
        return {
            "suiteId": "suite1",
            "projectId": "proj_resolved",
            "imported": [
                {"sourceRef": "a", "caseId": "c1", "publicId": "TC-1", "created": True},
                {"sourceRef": "b", "caseId": "c2", "publicId": "TC-2", "created": False},
            ],
            "stale": ["TC-9"],
        }

    def ingest_run(self, **kwargs: object) -> dict[str, object]:
        self.ingest_kwargs = kwargs
        return {"runId": "run1", "status": "FAIL", "projectId": "proj_resolved"}


@pytest.fixture()
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSdkClient]:
    module = types.ModuleType("suitest_sdk")
    module.SuitestClient = _FakeSdkClient  # type: ignore[attr-defined]
    module.SuitestAPIError = type("SuitestAPIError", (RuntimeError,), {})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suitest_sdk", module)
    return _FakeSdkClient


def _paths_with_code(tmp_path: Path) -> object:
    paths = build_paths(tmp_path / "suitest-output", Mode.BACKEND)
    paths.ensure()
    return paths


def test_publish_blocked_binding_inserts_nothing(tmp_path: Path, fake_sdk: object) -> None:
    cfg = _config(tmp_path)
    binding = rt.BindingResult("missing", "fail", detail="stale binding")
    _FakeSdkClient.last = None
    pub = publish_results(cfg, _run([]), _cases(), _paths_with_code(tmp_path), binding=binding)
    assert pub == {"published": False, "reason": "stale binding", "blocked": True}
    assert _FakeSdkClient.last is None  # no client, no API call, no inserts


def test_publish_retest_counts_and_classification(tmp_path: Path, fake_sdk: object) -> None:
    cfg = _config(tmp_path)
    binding = rt.BindingResult("valid", "reused_existing_project", project_id="proj_live")
    results = [
        TestResult("TC001", "create", "", TestOutcome.FAILED, 5, error="404 Not Found"),
    ]
    pub = publish_results(
        cfg,
        _run(results),
        _cases(),
        _paths_with_code(tmp_path),
        binding=binding,
        classifications={"TC001": "endpoint_not_found"},
    )
    assert pub["published"] is True
    assert (pub["created"], pub["reused"], pub["stale"]) == (1, 1, ["TC-9"])
    assert pub["runId"] == "run1" and pub["runStatus"] == "FAIL"
    client = _FakeSdkClient.last
    assert client is not None
    assert client.bulk_kwargs["project_id"] == "proj_live"
    assert client.bulk_kwargs["mark_stale"] is True
    sent = client.ingest_kwargs["results"]
    assert sent[0]["failureKind"] == "endpoint_not_found"  # type: ignore[index]


def test_publish_first_setup_by_slug_pins_project_id(tmp_path: Path, fake_sdk: object) -> None:
    cfg = _config(tmp_path, project_id="")
    binding = rt.BindingResult("first_setup", "will_create_by_slug")
    pub = publish_results(cfg, _run([]), _cases(), _paths_with_code(tmp_path), binding=binding)
    assert pub["published"] is True and pub["projectId"] == "proj_resolved"
    client = _FakeSdkClient.last
    assert client is not None
    assert client.bulk_kwargs["project_id"] == ""
    assert client.bulk_kwargs["project_slug"] == "demo-app"
    raw = json.loads(cfg.config_path.read_text())
    assert raw["publish"]["projectId"] == "proj_resolved"  # next run = explicit-id retest


def test_publish_empty_cases_never_marks_stale(tmp_path: Path, fake_sdk: object) -> None:
    cfg = _config(tmp_path)
    binding = rt.BindingResult("valid", "reused_existing_project", project_id="proj_live")
    publish_results(cfg, _run([]), [], _paths_with_code(tmp_path), binding=binding)
    client = _FakeSdkClient.last
    assert client is not None
    assert client.bulk_kwargs["mark_stale"] is False  # aborted run can't stale the suite


def test_publish_disabled_is_local_only(tmp_path: Path) -> None:
    cfg = _config(tmp_path, enabled=False)
    pub = publish_results(cfg, _run([]), _cases(), _paths_with_code(tmp_path))
    assert pub["published"] is False and pub["mode"] == "local_only"


# --------------------------------------------------------------------------- #
# 6. run_lifecycle gate: stale binding fails BEFORE anything runs
# --------------------------------------------------------------------------- #
def test_run_lifecycle_stale_binding_fails_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from suitest_lifecycle import orchestrator

    cfg = _config(tmp_path, project_id="proj_gone")
    missing = rt.BindingResult(
        "missing", "fail", project_id="proj_gone", detail="projectId 'proj_gone' not found"
    )
    monkeypatch.setattr(orchestrator, "resolve_binding", lambda *a, **k: missing)

    called = {"generate": False}

    def _boom(*a: object, **k: object) -> object:
        called["generate"] = True
        raise AssertionError("generation must not run on a stale binding")

    monkeypatch.setattr(orchestrator, "generate_only", _boom)
    res = orchestrator.run_lifecycle(cfg)
    assert res.success is False
    assert called["generate"] is False
    assert res.retest["mode"] == "blocked"
    assert res.retest["projectBinding"]["status"] == "missing"  # type: ignore[index]
    assert any("recreate" in a.lower() for a in res.retest["nextActions"])  # type: ignore[union-attr]


def test_build_retest_envelope_shape(tmp_path: Path) -> None:
    from suitest_lifecycle.orchestrator import _build_retest

    binding = rt.BindingResult("valid", "reused_existing_project", project_id="p1")
    report = {
        "changeDetection": {
            "first": False,
            "changed": True,
            "uiChanged": True,
            "apiChanged": True,
            "breaking": False,
            "changes": [{"kind": "route_added", "ref": "/x", "detail": ""}],
        },
        "generatedCode": {
            "new": 0,
            "regenerated": 3,
            "unchanged": 8,
            "reused": 0,
            "needs_review": 0,
        },
    }
    pub = {
        "published": True,
        "runId": "r1",
        "runStatus": "FAIL",
        "created": 0,
        "reused": 8,
        "stale": ["TC-9"],
    }
    data = _build_retest(binding, report, {"TC001": "selector_changed"}, pub)
    assert data["mode"] == "retest"
    assert data["projectBinding"] == {
        "status": "valid",
        "action": "reused_existing_project",
        "projectId": "p1",
    }
    assert data["failureClassification"] == ["selector_changed"]
    assert data["testCases"] == {"created": 0, "reused": 8, "stale": 1}
    assert data["testRun"] == {"created": True, "runId": "r1", "status": "FAIL"}
    assert data["changeDetection"]["uiChanged"] is True  # type: ignore[index]


# --------------------------------------------------------------------------- #
# 7. selector-level change detection (crawl/blackbox element fingerprint)
# --------------------------------------------------------------------------- #
def _elements(v: str = "a") -> dict[str, object]:
    return {
        "/login": {"elements": {"inputs": ["#email", "#password"], "buttons": ["#submit"]}},
        "/dashboard": {"elements": {"buttons": [f"#refresh-{v}"]}},
    }


def test_element_fingerprint_unchanged_is_clean() -> None:
    fp1 = rt.build_fingerprint(_summary(), _cases(), _elements())
    fp2 = rt.build_fingerprint(_summary(), _cases(), _elements())
    assert rt.diff_fingerprint(fp1, fp2)["changed"] is False


def test_element_fingerprint_selector_change_detected() -> None:
    prev = rt.build_fingerprint(_summary(), _cases(), _elements("a"))
    cur = rt.build_fingerprint(_summary(), _cases(), _elements("b"))
    report = rt.diff_fingerprint(prev, cur)
    assert _kinds(report) == {"selector_changed"}
    assert report["uiChanged"] is True and report["breaking"] is False
    refs = [c["ref"] for c in report["changes"]]  # type: ignore[index, union-attr]
    assert refs == ["/dashboard"]  # only the route whose elements moved


def test_element_fingerprint_absent_capture_never_false_positives() -> None:
    # Old snapshot from a repo-analysis run (no element capture) vs new crawl.
    prev = rt.build_fingerprint(_summary(), _cases())
    cur = rt.build_fingerprint(_summary(), _cases(), _elements())
    assert rt.diff_fingerprint(prev, cur)["changed"] is False


def test_crawl_elements_extraction() -> None:
    from suitest_lifecycle.orchestrator import _crawl_elements

    class FakeCrawl:
        def __init__(self) -> None:
            self.page_elements = {"/login": {"inputs": ["#email"]}}
            self.page_testids = {"/login": ["login-btn"], "/home": ["nav"]}

    out = _crawl_elements(FakeCrawl())
    assert out is not None and set(out) == {"/login", "/home"}
    assert out["/login"] == {"elements": {"inputs": ["#email"]}, "testids": ["login-btn"]}
    assert _crawl_elements(None) is None
    assert _crawl_elements(object()) is None  # no capture -> no fingerprint section


def test_discovery_elements_exclude_volatile_fields() -> None:
    from suitest_lifecycle.blackbox.models import ElementInfo, PageInfo
    from suitest_lifecycle.orchestrator import _discovery_elements

    def _page(screenshot: str, link_text: str, button_text: str = "Save") -> PageInfo:
        return PageInfo(
            route="/items",
            inputs=[ElementInfo(kind="input", name="q", css="#q")],
            buttons=[ElementInfo(kind="button", text=button_text, css="#save")],
            links=[ElementInfo(kind="link", href="/items/1", text=link_text, css="a.row")],
            has_table=True,
            screenshot=screenshot,
        )

    run1 = _discovery_elements([_page("shot-001.png", "Item #1 (3 comments)")])
    run2 = _discovery_elements([_page("shot-999.png", "Item #1 (7 comments)")])
    assert run1 == run2  # screenshots + dynamic link text never churn the digest
    changed = _discovery_elements([_page("shot-001.png", "x", button_text="Submit")])
    assert changed != run1  # button LABEL is part of the UI contract


# --------------------------------------------------------------------------- #
# 8. blackbox publish binding gate
# --------------------------------------------------------------------------- #
class _FakeBlackboxSdk:
    last: ClassVar[_FakeBlackboxSdk | None] = None
    resolve_response: ClassVar[dict[str, object]] = {"status": "missing"}

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.resolve_calls: list[dict[str, str]] = []
        self.bulk_kwargs: dict[str, object] | None = None
        self.ingest_kwargs: dict[str, object] | None = None
        _FakeBlackboxSdk.last = self

    def __enter__(self) -> _FakeBlackboxSdk:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def resolve_project(self, **kwargs: str) -> dict[str, object]:
        self.resolve_calls.append(dict(kwargs))
        return dict(_FakeBlackboxSdk.resolve_response)

    def upload_file(self, path: str, *, content_type: str | None = None) -> str:
        return "s3://fake/" + path

    def bulk_import_cases(self, **kwargs: object) -> dict[str, object]:
        self.bulk_kwargs = kwargs
        return {"suiteId": "s1", "projectId": "proj_bb", "imported": [], "stale": []}

    def ingest_run(self, **kwargs: object) -> dict[str, object]:
        self.ingest_kwargs = kwargs
        return {"runId": "run_bb", "status": "PASS"}


@pytest.fixture()
def blackbox_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    module = types.ModuleType("suitest_sdk")
    module.SuitestClient = _FakeBlackboxSdk  # type: ignore[attr-defined]
    module.SuitestAPIError = type("SuitestAPIError", (RuntimeError,), {})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suitest_sdk", module)
    monkeypatch.setenv("SUITEST_API_URL", "http://localhost:4000")
    monkeypatch.setenv("SUITEST_API_KEY", "sk-test")

    cfg_file = tmp_path / "suitest.config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "mode": "frontend",
                "projectName": "Demo App",
                "baseUrl": "http://demo.local:3000",
                "server": {"autostart": False},
                "output": "suitest-output",
                "publish": {"enabled": True, "projectId": "proj_gone"},
            }
        ),
        encoding="utf-8",
    )
    paths = build_paths(tmp_path / "suitest-output", Mode.FRONTEND)
    paths.ensure()
    paths.test_plan_json.write_text(
        json.dumps(
            [
                {
                    "id": "TC001",
                    "title": "smoke_home_loads",
                    "description": "",
                    "category": "Blackbox",
                    "priority": "High",
                    "steps": [],
                    "source_ref": "bb:/",
                    "automation_file": "",
                }
            ]
        ),
        encoding="utf-8",
    )
    return cfg_file


def test_blackbox_publish_stale_binding_blocks(blackbox_env: Path) -> None:
    from suitest_lifecycle.blackbox.mcp import blackbox_publish_results

    _FakeBlackboxSdk.resolve_response = {"status": "missing", "candidates": []}
    out = blackbox_publish_results(config_path=str(blackbox_env))
    assert out["success"] is False
    assert "stale project binding" in out["summary"]
    client = _FakeBlackboxSdk.last
    assert client is not None and client.bulk_kwargs is None  # nothing inserted
    assert out["data"]["projectBinding"]["status"] == "missing"


def test_blackbox_publish_repaired_binding_rewrites_config(blackbox_env: Path) -> None:
    from suitest_lifecycle.blackbox.mcp import blackbox_publish_results

    _FakeBlackboxSdk.resolve_response = {
        "status": "repaired",
        "projectId": "proj_fixed",
        "matchedBy": "slug",
    }
    out = blackbox_publish_results(config_path=str(blackbox_env))
    assert out["success"] is True
    client = _FakeBlackboxSdk.last
    assert client is not None and client.bulk_kwargs is not None
    assert client.bulk_kwargs["project_id"] == "proj_fixed"
    assert client.bulk_kwargs["project_slug"] == ""  # validated id never degrades to slug
    raw = json.loads(blackbox_env.read_text())
    assert raw["publish"]["projectId"] == "proj_fixed"


def test_blackbox_publish_recreate_only_with_flag(blackbox_env: Path) -> None:
    from suitest_lifecycle.blackbox.mcp import blackbox_publish_results

    _FakeBlackboxSdk.resolve_response = {"status": "missing", "candidates": []}
    out = blackbox_publish_results(config_path=str(blackbox_env), recreate_project=True)
    assert out["success"] is True
    client = _FakeBlackboxSdk.last
    assert client is not None and client.bulk_kwargs is not None
    assert client.bulk_kwargs["project_id"] == ""  # by-slug find-or-create
    assert client.bulk_kwargs["project_slug"] == "demo-local-3000"
    assert out["data"]["projectBinding"]["status"] == "recreate_requested"
    raw = json.loads(blackbox_env.read_text())
    assert raw["publish"]["projectId"] == "proj_bb"  # minted id pinned for next retest
