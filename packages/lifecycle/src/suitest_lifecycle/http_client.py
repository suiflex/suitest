"""Stdlib-only Suitest API client for the bundled lifecycle.

Mirrors the slice of the ``suiflex-suitest-sdk`` surface the lifecycle needs
(binding resolve, bulk import, run ingest, artifact upload, LLM proxy) using
only ``urllib`` — so ``npx @suiflex/suitest-mcp`` publishes out of the box,
with zero ``pip install`` on the host. The pip SDK remains the richer client
for external integrations; this one exists so a brand-new QA user's first run
lands in the web UI instead of silently skipping publish.
"""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

JSONDict = dict[str, Any]


class SuitestAPIError(RuntimeError):
    """Raised on a non-2xx API response. Carries status + parsed body."""

    def __init__(self, status_code: int, body: object) -> None:
        super().__init__(f"Suitest API error {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class SuitestClient:
    """Drop-in for the SDK client's lifecycle-facing methods (sync, stdlib)."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        workspace_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._headers: dict[str, str] = {"Accept": "application/json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        if workspace_id:
            self._headers["X-Workspace-Id"] = workspace_id

    def __enter__(self) -> SuitestClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:  # urllib is connectionless — kept for SDK parity
        return None

    # -- low level ----------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: JSONDict | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        url = self._base + path
        if params:
            url += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items()})
        hdrs = dict(self._headers)
        body: bytes | None = data
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
                if resp.status == 204 or not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed: object = json.loads(raw)
            except ValueError:
                parsed = raw.decode("utf-8", errors="replace")
            raise SuitestAPIError(exc.code, parsed) from exc

    # -- LLM proxy ------------------------------------------------------------
    def llm_complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        body: JSONDict = {"prompt": prompt, "maxTokens": max_tokens, "temperature": temperature}
        if system is not None:
            body["system"] = system
        result = self._request("POST", "/api/v1/llm/complete", json_body=body)
        return str(result.get("content", "")) if isinstance(result, dict) else ""

    # -- lifecycle ingest -----------------------------------------------------
    def resolve_project(
        self, *, project_id: str = "", project_slug: str = "", project_name: str = ""
    ) -> JSONDict:
        result = self._request(
            "POST",
            "/api/v1/ingest/resolve-project",
            json_body={
                "projectId": project_id,
                "projectSlug": project_slug,
                "projectName": project_name,
            },
        )
        return result if isinstance(result, dict) else {}

    def bulk_import_cases(
        self,
        *,
        project_id: str = "",
        suite_name: str,
        mode: str,
        cases: list[JSONDict],
        project_slug: str = "",
        project_name: str = "",
        mark_stale: bool = False,
    ) -> JSONDict:
        result = self._request(
            "POST",
            "/api/v1/test-cases/bulk-import",
            json_body={
                "projectId": project_id,
                "projectSlug": project_slug,
                "projectName": project_name,
                "suiteName": suite_name,
                "mode": mode,
                "cases": cases,
                "markStale": mark_stale,
            },
        )
        return result if isinstance(result, dict) else {}

    def ingest_run(
        self,
        *,
        project_id: str = "",
        suite_name: str,
        name: str,
        results: list[JSONDict],
        env: str = "staging",
        branch: str | None = None,
        commit_sha: str | None = None,
        project_slug: str = "",
        project_name: str = "",
    ) -> JSONDict:
        body: JSONDict = {
            "projectId": project_id,
            "projectSlug": project_slug,
            "projectName": project_name,
            "suiteName": suite_name,
            "name": name,
            "env": env,
            "results": results,
        }
        if branch is not None:
            body["branch"] = branch
        if commit_sha is not None:
            body["commitSha"] = commit_sha
        result = self._request("POST", "/api/v1/runs/ingest", json_body=body)
        return result if isinstance(result, dict) else {}

    def upload_file(self, path: str, *, content_type: str | None = None) -> str:
        """Multipart upload to /api/v1/files; returns the durable s3:// URL.

        The whole file is buffered in memory — run videos are a few MB, fine.
        """
        ct = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        boundary = uuid.uuid4().hex
        name = os.path.basename(path)
        with open(path, "rb") as fh:
            payload = fh.read()
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: {ct}\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        result = self._request(
            "POST",
            "/api/v1/files",
            data=head + payload + tail,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        if not isinstance(result, dict):
            raise SuitestAPIError(0, "unexpected upload response")
        return str(result["url"])
