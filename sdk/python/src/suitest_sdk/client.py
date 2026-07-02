"""Synchronous Suitest API client (M4-5)."""

from __future__ import annotations

import time
from typing import Any

import httpx

JSONDict = dict[str, Any]


class SuitestAPIError(RuntimeError):
    """Raised on a non-2xx API response. Carries status + parsed body."""

    def __init__(self, status_code: int, body: object) -> None:
        super().__init__(f"Suitest API error {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class SuitestClient:
    """Typed httpx client over the Suitest REST API.

    Args:
        base_url: Root URL of the Suitest API, e.g. ``https://suitest.example``.
        token: Bearer token (session JWT / API token).
        workspace_id: Sent as ``X-Workspace-Id`` on every request.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        workspace_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        headers: dict[str, str] = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if workspace_id:
            headers["X-Workspace-Id"] = workspace_id
        self._http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)

    def __enter__(self) -> SuitestClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # -- low level ----------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._http.request(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                body: object = resp.json()
            except ValueError:
                body = resp.text
            raise SuitestAPIError(resp.status_code, body)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # -- health / capabilities ---------------------------------------------
    def health(self) -> JSONDict:
        return self._request("GET", "/health")

    def capabilities(self) -> JSONDict:
        return self._request("GET", "/capabilities")

    # -- test cases ---------------------------------------------------------
    def list_cases(self, *, limit: int = 50) -> list[JSONDict]:
        page = self._request("GET", "/api/v1/test-cases", params={"limit": limit})
        items = page.get("items", []) if isinstance(page, dict) else []
        return [i for i in items if isinstance(i, dict)]

    def search_cases(self, query: str, *, limit: int = 10) -> list[JSONDict]:
        return self._request(
            "GET", "/api/v1/test-cases/search", params={"q": query, "limit": limit}
        )

    # -- runs ---------------------------------------------------------------
    def create_run(self, *, case_id: str) -> JSONDict:
        return self._request("POST", f"/api/v1/test-cases/{case_id}/runs")

    def create_run_selection(
        self,
        *,
        project_id: str,
        name: str,
        case_ids: list[str],
        branch: str | None = None,
    ) -> JSONDict:
        """Trigger a multi-case run via ``POST /runs`` (project + case selection)."""
        body: JSONDict = {
            "projectId": project_id,
            "name": name,
            "selection": [{"caseId": cid} for cid in case_ids],
        }
        if branch is not None:
            body["branch"] = branch
        return self._request("POST", "/api/v1/runs", json=body)

    def get_run(self, run_id: str) -> JSONDict:
        return self._request("GET", f"/api/v1/runs/{run_id}")

    def wait_for_run(
        self, run_id: str, *, poll_interval: float = 2.0, timeout: float = 600.0
    ) -> JSONDict:
        """Poll a run until it reaches a terminal status or ``timeout`` elapses."""
        deadline = time.monotonic() + timeout
        terminal = {"PASSED", "FAILED", "CANCELLED", "ERROR"}
        while True:
            run = self.get_run(run_id)
            status = str(run.get("status", "")).upper()
            if status in terminal or time.monotonic() >= deadline:
                return run
            time.sleep(poll_interval)

    # -- LLM proxy (lifecycle enrichment / codegen) ---------------------------
    def llm_complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        """One-shot completion via the workspace's active LLM (server-side key).

        Raises :class:`SuitestAPIError` with status 409 when the workspace has
        no LLM configured (ZERO tier) — callers degrade to deterministic paths.
        Returns the completion text.
        """
        body: JSONDict = {
            "prompt": prompt,
            "maxTokens": max_tokens,
            "temperature": temperature,
        }
        if system is not None:
            body["system"] = system
        result = self._request("POST", "/api/v1/llm/complete", json=body)
        return str(result.get("content", ""))

    # -- lifecycle ingest (Phase 2) -----------------------------------------
    def bulk_import_cases(
        self,
        *,
        project_id: str = "",
        suite_name: str,
        mode: str,
        cases: list[JSONDict],
        project_slug: str = "",
        project_name: str = "",
    ) -> JSONDict:
        """Upsert a suite's generated cases + steps (idempotent by sourceRef).

        Target project: pass ``project_id``, or ``project_slug`` (+ optional
        display name) and the server finds-or-creates it in the workspace.
        """
        body: JSONDict = {
            "projectId": project_id,
            "projectSlug": project_slug,
            "projectName": project_name,
            "suiteName": suite_name,
            "mode": mode,
            "cases": cases,
        }
        return self._request("POST", "/api/v1/test-cases/bulk-import", json=body)

    def upload_file(self, path: str, *, content_type: str | None = None) -> str:
        """Upload a local file to the workspace object store; return its s3:// URL.

        The server holds the S3 credentials — the client only needs its API key.
        Used by the lifecycle publisher for run videos + per-step screenshots so
        no ``SUITEST_S3_*`` env is required client-side.
        """
        import mimetypes
        import os

        ct = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            result = self._request(
                "POST",
                "/api/v1/files",
                files={"file": (os.path.basename(path), fh, ct)},
            )
        url: str = result["url"]
        return url

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
        """Record an already-completed lifecycle run (no ARQ execution).

        Target project mirrors :meth:`bulk_import_cases` — id, or
        find-or-create by ``project_slug``.
        """
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
        return self._request("POST", "/api/v1/runs/ingest", json=body)

    # -- mcp ----------------------------------------------------------------
    def list_mcp_providers(self) -> list[JSONDict]:
        result = self._request("GET", "/api/v1/mcp/providers")
        if isinstance(result, list):
            return [r for r in result if isinstance(r, dict)]
        items = result.get("items", []) if isinstance(result, dict) else []
        return [i for i in items if isinstance(i, dict)]
