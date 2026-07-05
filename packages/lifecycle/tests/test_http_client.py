"""Loopback tests for the stdlib publish client (no third-party deps)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from suitest_lifecycle.http_client import SuitestAPIError, SuitestClient

_seen: dict[str, Any] = {}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        _seen["path"] = self.path
        _seen["auth"] = self.headers.get("Authorization")
        _seen["content_type"] = self.headers.get("Content-Type")
        _seen["body"] = body
        if self.path == "/api/v1/boom":
            payload = json.dumps({"detail": "nope"}).encode()
            self.send_response(422)
        elif self.path == "/api/v1/files":
            payload = json.dumps({"url": "s3://bucket/video.webm"}).encode()
            self.send_response(200)
        else:
            payload = json.dumps({"runId": "r1", "status": "PASS"}).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:  # keep pytest output clean
        return


@pytest.fixture()
def server_url() -> Any:
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_json_post_carries_auth_and_body(server_url: str) -> None:
    with SuitestClient(server_url, token="sk_x", workspace_id="ws1") as c:
        result = c.ingest_run(suite_name="s", name="n", results=[{"slug": "a"}])
    assert result["runId"] == "r1"
    assert _seen["auth"] == "Bearer sk_x"
    sent = json.loads(_seen["body"])
    assert sent["suiteName"] == "s" and sent["results"] == [{"slug": "a"}]


def test_http_error_maps_to_api_error(server_url: str) -> None:
    client = SuitestClient(server_url)
    with pytest.raises(SuitestAPIError) as exc:
        client._request("POST", "/api/v1/boom", json_body={})
    assert exc.value.status_code == 422
    assert exc.value.body == {"detail": "nope"}


def test_upload_file_multipart(server_url: str, tmp_path: Any) -> None:
    f = tmp_path / "video.webm"
    f.write_bytes(b"\x1aEwebm-bytes")
    url = SuitestClient(server_url).upload_file(str(f))
    assert url == "s3://bucket/video.webm"
    ct = _seen["content_type"]
    assert ct.startswith("multipart/form-data; boundary=")
    boundary = ct.split("boundary=")[1]
    raw = _seen["body"]
    assert boundary.encode() in raw
    assert b'filename="video.webm"' in raw
    assert b"\x1aEwebm-bytes" in raw
