"""Tests for static SPA serving when SUITEST_WEB_DIST is set (Task 5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from suitest_api.main import create_app


def test_serves_index_when_web_dist_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = tmp_path / "web"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>suitest</title>", encoding="utf-8")
    monkeypatch.setenv("SUITEST_WEB_DIST", str(dist))

    app = create_app()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "suitest" in resp.text


def test_spa_deep_link_falls_back_to_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = tmp_path / "web"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>suitest</title>", encoding="utf-8")
    monkeypatch.setenv("SUITEST_WEB_DIST", str(dist))

    app = create_app()
    client = TestClient(app)
    resp = client.get("/cases/123")  # client-side route, no such file
    assert resp.status_code == 200
    assert "suitest" in resp.text


def test_api_routes_still_work_under_static_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "web"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setenv("SUITEST_WEB_DIST", str(dist))

    app = create_app()
    client = TestClient(app)
    # /health is the inline liveness probe — registered before the SPA mount
    resp = client.get("/health")
    assert resp.status_code in (200, 401)  # route exists (ok/auth) — NOT the SPA html
    assert "<!doctype html>" not in resp.text


def test_unknown_api_path_404s_instead_of_reaching_the_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A POST to a route the running API lacks must not answer 405 from StaticFiles.

    StaticFiles rejects every non-GET before it looks at the path, so an API and a
    web bundle built from different revisions used to report the missing route as
    "Method Not Allowed" — which reads like a bug in a route that exists.
    """
    dist = tmp_path / "web"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setenv("SUITEST_WEB_DIST", str(dist))

    app = create_app()
    client = TestClient(app)
    resp = client.post("/api/v1/no-such-route", json={})
    assert resp.status_code == 404, resp.text
    assert "older than the web bundle" in resp.json()["detail"]

    # GET must not silently serve the SPA for an API path either — a JSON caller
    # parsing index.html is no easier to diagnose than the 405 was.
    get = client.get("/api/v1/no-such-route")
    assert get.status_code == 404
    assert "<!doctype html>" not in get.text
