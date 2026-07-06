"""Tests for static SPA serving when SUITEST_WEB_DIST is set (Task 5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from suitest_api.main import create_app


def test_serves_index_when_web_dist_set(tmp_path, monkeypatch) -> None:
    dist = tmp_path / "web"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>suitest</title>", encoding="utf-8")
    monkeypatch.setenv("SUITEST_WEB_DIST", str(dist))

    app = create_app()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "suitest" in resp.text


def test_spa_deep_link_falls_back_to_index(tmp_path, monkeypatch) -> None:
    dist = tmp_path / "web"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>suitest</title>", encoding="utf-8")
    monkeypatch.setenv("SUITEST_WEB_DIST", str(dist))

    app = create_app()
    client = TestClient(app)
    resp = client.get("/cases/123")  # client-side route, no such file
    assert resp.status_code == 200
    assert "suitest" in resp.text


def test_api_routes_still_work_under_static_mount(tmp_path, monkeypatch) -> None:
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
