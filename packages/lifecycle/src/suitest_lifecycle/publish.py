"""Publish lifecycle results into a running Suitest (Approach A — REST ingest).

Builds the bulk-import (cases + steps + source code) and run-ingest (completed
run + per-step outcomes + video/screenshot artifacts) payloads, then sends them
via the bundled stdlib client (:mod:`suitest_lifecycle.http_client`) — no pip
install needed on the host, so ``npx @suiflex/suitest-mcp`` publishes out of
the box. If the server is unavailable, publishing degrades to a clean
``{"published": False, "reason": ...}`` instead of failing the run.
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from suitest_lifecycle.config import Config
    from suitest_lifecycle.http_client import SuitestClient
    from suitest_lifecycle.models import PlanCase, RunSummary, TestResult
    from suitest_lifecycle.paths import Paths
    from suitest_lifecycle.retest import BindingResult


class Uploader(Protocol):
    """Minimal upload surface the publisher needs (satisfied by SuitestClient).

    Artifacts go THROUGH the API — the server holds the S3 credentials, so the
    lifecycle/MCP client needs no ``SUITEST_S3_*`` env of its own.
    """

    def upload_file(self, path: str, *, content_type: str | None = None) -> str: ...


_PRIORITY = {"High": "P1", "Medium": "P2", "Low": "P3"}
_MIME = {".webm": "video/webm", ".png": "image/png", ".jpg": "image/jpeg"}

# PlanCase.title is the generated test function slug (codegen emits
# ``test_<title>``), so the publish layer is where the human display title is
# minted: ``slug`` carries the technical key, ``title`` the readable sentence.
# Mirrors suitest_shared.text.humanize_slug (lifecycle stays stdlib-only).
_ACRONYMS = frozenset({"api", "url", "id", "ui", "ux", "http", "sql", "ok", "sso", "mcp"})


def _humanize(slug: str) -> str:
    words = [w for w in slug.replace("_", " ").replace("-", " ").split() if w]
    if not words:
        return slug.strip()
    out: list[str] = []
    for i, word in enumerate(words):
        lower = word.lower()
        if lower in _ACRONYMS:
            out.append(lower.upper())
        elif i == 0:
            out.append(word[:1].upper() + word[1:].lower())
        else:
            out.append(lower)
    return " ".join(out)


def _suite_name(config: Config) -> str:
    return config.publish.suite_name or f"{config.project_name} {config.mode.value}"


def _sanitize_automation_code(code: str) -> str:
    """Prevent credentials embedded by pre-fix generators from entering the DB."""
    lines = code.splitlines(keepends=True)
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("USERNAME =") and "os.environ" not in stripped:
            lines[index] = 'USERNAME = os.environ.get("SUITEST_TEST_USERNAME", "")\n'
            replaced = True
        elif stripped.startswith("PASSWORD =") and "os.environ" not in stripped:
            lines[index] = 'PASSWORD = os.environ.get("SUITEST_TEST_PASSWORD", "")\n'
            replaced = True
    sanitized = "".join(lines)
    if replaced and not any(line.strip() == "import os" for line in lines):
        sanitized = "import os\n" + sanitized
    return sanitized


def _case_payloads(cases: list[PlanCase], paths: Paths) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for c in cases:
        code = ""
        if c.automation_file:
            fp = paths.test_file(c.automation_file)
            if fp.is_file():
                code = _sanitize_automation_code(fp.read_text(encoding="utf-8"))
        out.append(
            {
                "sourceRef": c.source_ref,
                # ``name`` stays the slug — it is the server's idempotency match
                # key for rows published before the title/slug split.
                "name": c.title,
                "slug": c.title,
                "title": _humanize(c.title),
                "description": c.description,
                # Lifecycle cases are produced by the MCP-native plan/run loop, so
                # they surface under the MCP filter (not the generic IMPORT bucket).
                "source": "MCP",
                "priority": _PRIORITY.get(c.priority.value, "P2"),
                "category": c.category,
                "tags": list(c.tags),
                "automationFilePath": c.automation_file,
                "automationCode": code,
                "generatedBy": "suitest-lifecycle",
                "steps": [
                    {
                        "order": i + 1,
                        "action": s.description,
                        # For assertions the description *is* the expectation; for
                        # actions there's no distinct expected, so leave it blank
                        # and let the reader derive one.
                        "expected": s.description if s.type == "assertion" else "",
                        "code": None,
                    }
                    for i, s in enumerate(c.steps)
                ],
            }
        )
    return out


def _resolve_url(client: Uploader, path: str, mime: str) -> str:
    """Upload the artifact THROUGH the API (server owns the storage creds — local
    disk, S3, or MinIO) and return the durable URL. Deletion deliberately does
    NOT happen here: an upload without the matching run-result DB commit is an
    orphan, not a completed publish. ``PublishSession.append`` removes scratch
    evidence only after both operations succeed. On an upload hiccup the local
    file remains and a cross-platform ``file://`` reference is returned."""
    try:
        return client.upload_file(path, content_type=mime)
    except Exception:  # never fail publish on an upload hiccup
        return Path(path).resolve().as_uri()  # correct file:// URI on all OSes


def _artifact(client: Uploader, path: str, kind: str) -> dict[str, object] | None:
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    mime = _MIME.get(ext, "application/octet-stream")
    size = os.path.getsize(path)
    return {
        "kind": kind,
        "url": _resolve_url(client, path, mime),
        "mimeType": mime,
        "sizeBytes": size,
    }


def _result_payloads(
    client: Uploader,
    summary: RunSummary,
    cases: list[PlanCase],
    classifications: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    kinds = classifications or {}
    return [
        _result_payload(client, result, cases, kinds.get(result.test_id, ""))
        for result in summary.results
    ]


def _result_payload(
    client: Uploader,
    result: TestResult,
    cases: list[PlanCase],
    classification: str = "",
) -> dict[str, object]:
    """Upload and shape exactly one completed test result."""
    ref_by_id = {case.id: case.source_ref for case in cases}
    name_by_id = {case.id: case.title for case in cases}
    # Case level carries only the VIDEO now; screenshots are per-step (each
    # run_step gets its own SCREENSHOT), so the "final" one would be redundant.
    artifacts = [
        artifact
        for artifact in (_artifact(client, result.video_path, "VIDEO"),)
        if artifact is not None
    ]
    slug = name_by_id.get(result.test_id, result.title)
    return {
        "name": slug,
        "slug": slug,
        "sourceRef": ref_by_id.get(result.test_id, result.test_id),
        "outcome": result.status.value,
        "durationMs": result.duration_ms,
        "error": result.error,
        "failureKind": classification,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "steps": [
            {
                "order": step.index,
                "type": step.type,
                "description": step.description,
                "outcome": step.status.value,
                # Per-step screenshot, uploaded so the web can sign + show it.
                "screenshot": (
                    _resolve_url(client, step.screenshot_path, "image/png")
                    if step.screenshot_path and os.path.isfile(step.screenshot_path)
                    else ""
                ),
                "screenshotSizeBytes": (
                    os.path.getsize(step.screenshot_path)
                    if step.screenshot_path and os.path.isfile(step.screenshot_path)
                    else 0
                ),
            }
            for step in result.steps
        ],
        "artifacts": artifacts,
    }


def _durable(url: object) -> bool:
    return isinstance(url, str) and bool(url) and not url.startswith("file:")


def _unlink(path: str) -> None:
    if not path:
        return
    with suppress(OSError):
        Path(path).unlink(missing_ok=True)


def _cleanup_committed_result(result: TestResult, payload: dict[str, object], paths: Paths) -> None:
    """Drop only evidence whose blob URL and result row are both durable."""
    artifacts = payload.get("artifacts")
    video_path = result.video_path
    video_durable = False
    if isinstance(artifacts, list) and artifacts and isinstance(artifacts[0], dict):
        video_durable = _durable(artifacts[0].get("url"))
    if video_durable:
        _unlink(video_path)
        # Each test owns one video directory. Removing it also clears stale
        # Playwright recordings left by interrupted/older runs.
        video_dir = Path(video_path).parent
        try:
            if video_dir.resolve().is_relative_to(paths.tmp_dir.resolve()):
                for stale_video in video_dir.rglob("*.webm"):
                    _unlink(str(stale_video))
                for directory in sorted(
                    (p for p in video_dir.rglob("*") if p.is_dir()),
                    key=lambda p: len(p.parts),
                    reverse=True,
                ):
                    with suppress(OSError):
                        directory.rmdir()
                with suppress(OSError):
                    video_dir.rmdir()
        except OSError:
            pass

    payload_steps = payload.get("steps")
    result_steps = result.steps
    if isinstance(payload_steps, list):
        for step, sent in zip(result_steps, payload_steps, strict=False):
            if isinstance(sent, dict) and _durable(sent.get("screenshot")):
                _unlink(step.screenshot_path)

    # The final screenshot is not published because the final recorded step is
    # already the preview. It is safe to discard once this result committed.
    _unlink(result.screenshot_path)


def cleanup_transient_media(paths: Paths) -> None:
    """Remove ephemeral browser media after a fully successful publish."""
    if not paths.tmp_dir.is_dir():
        return
    for pattern in ("*.png", "*.webm", "*.zip"):
        for candidate in paths.tmp_dir.rglob(pattern):
            _unlink(str(candidate))
    # Bottom-up empty-dir removal; JSON/report files remain untouched.
    for directory in sorted(
        (p for p in paths.tmp_dir.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        with suppress(OSError):
            directory.rmdir()


class PublishSession:
    """Case-first, per-test publisher backed by one durable Suitest run."""

    def __init__(
        self,
        config: Config,
        cases: list[PlanCase],
        paths: Paths,
        *,
        binding: BindingResult | None = None,
    ) -> None:
        self.config = config
        self.cases = cases
        self.paths = paths
        self.binding = binding
        self.client: SuitestClient | None = None
        self.project_id = ""
        self.run_id = ""
        self.run_status = "RUNNING"
        self.created = 0
        self.reused = 0
        self.stale: list[object] = []
        self.appended = 0
        self.reason = ""

    def start(self) -> dict[str, object]:
        """Upsert cases and create the RUNNING row before test execution."""
        if not self.config.publish.enabled:
            self.reason = "publish disabled"
            return {"started": False, "reason": self.reason, "mode": "local_only"}
        if self.binding is not None and self.binding.blocks_publish:
            self.reason = self.binding.detail
            return {"started": False, "reason": self.reason, "blocked": True}
        if self.binding is None and not self.config.publish.project_id:
            self.reason = "publish.projectId not set"
            return {"started": False, "reason": self.reason}

        from suitest_lifecycle.http_client import SuitestClient
        from suitest_lifecycle.retest import project_slug, rewrite_project_id

        by_slug = self.binding is not None and self.binding.status in (
            "first_setup",
            "recreate_requested",
        )
        bound_id = (
            ""
            if by_slug
            else (
                self.binding.project_id
                if self.binding is not None
                else self.config.publish.project_id
            )
        )
        slug = project_slug(self.config.project_name) if by_slug else ""
        api_url = self.config.publish.api_url or os.environ.get("SUITEST_API_URL", "")
        token = self.config.publish.token or os.environ.get("SUITEST_API_KEY") or None
        client = SuitestClient(
            api_url,
            token=token,
            workspace_id=self.config.publish.workspace_id or None,
            timeout=180.0,
        )
        self.client = client
        client.__enter__()
        try:
            imported = client.bulk_import_cases(
                project_id=bound_id,
                project_slug=slug,
                project_name=self.config.project_name if by_slug else "",
                suite_name=_suite_name(self.config),
                mode=self.config.mode.value,
                cases=_case_payloads(self.cases, self.paths),
                mark_stale=bool(self.cases),
            )
            self.project_id = str(imported.get("projectId", "") or "") or bound_id
            rows = imported.get("imported", [])
            imported_rows = rows if isinstance(rows, list) else []
            self.created = sum(
                1 for row in imported_rows if isinstance(row, dict) and row.get("created")
            )
            self.reused = len(imported_rows) - self.created
            stale = imported.get("stale", [])
            self.stale = stale if isinstance(stale, list) else []
            started = client.ingest_run(
                project_id=self.project_id,
                suite_name=_suite_name(self.config),
                name=f"{self.config.project_name} lifecycle",
                results=[],
                finalize=False,
            )
            self.run_id = str(started.get("runId", "") or "")
            self.run_status = str(started.get("status", "RUNNING") or "RUNNING")
            if not self.run_id:
                raise RuntimeError("server did not return a runId")
        except Exception as exc:
            self.reason = f"connection error: {type(exc).__name__}: {exc}"
            self.close()
            return {"started": False, "reason": self.reason}

        if by_slug and self.project_id and self.project_id != self.config.publish.project_id:
            rewrite_project_id(self.config.config_path, self.project_id)
        return {
            "started": True,
            "projectId": self.project_id,
            "runId": self.run_id,
            "imported": self.created + self.reused,
            "created": self.created,
            "reused": self.reused,
            "stale": self.stale,
        }

    def append(self, result: TestResult, *, classification: str = "") -> bool:
        """Upload + append one test, then release its committed scratch media."""
        if self.client is None or not self.run_id or self.reason:
            return False
        payload = _result_payload(self.client, result, self.cases, classification)
        try:
            response = self.client.ingest_run(
                run_id=self.run_id,
                finalize=False,
                project_id=self.project_id,
                suite_name=_suite_name(self.config),
                name=f"{self.config.project_name} lifecycle",
                results=[payload],
            )
        except Exception as exc:
            # Keep local scratch: the result row did not commit, so the publish
            # is not durable even if its blob upload happened to finish.
            self.reason = f"incremental publish failed: {type(exc).__name__}: {exc}"
            return False
        self.run_status = str(response.get("status", "RUNNING") or "RUNNING")
        self.appended += 1
        _cleanup_committed_result(result, payload, self.paths)
        return True

    def finish(self) -> dict[str, object]:
        """Finalize counters/status after the last result."""
        if self.client is None or not self.run_id:
            return {"published": False, "reason": self.reason or "publish not started"}
        if self.reason:
            self.close()
            return {
                "published": False,
                "reason": self.reason,
                "projectId": self.project_id,
                "runId": self.run_id,
                "partial": self.appended,
            }
        try:
            run = self.client.ingest_run(
                run_id=self.run_id,
                finalize=True,
                project_id=self.project_id,
                suite_name=_suite_name(self.config),
                name=f"{self.config.project_name} lifecycle",
                results=[],
            )
            self.run_status = str(run.get("status", "") or "")
        except Exception as exc:
            self.reason = f"finalize publish failed: {type(exc).__name__}: {exc}"
            self.close()
            return {
                "published": False,
                "reason": self.reason,
                "projectId": self.project_id,
                "runId": self.run_id,
                "partial": self.appended,
            }
        self.close()
        cleanup_transient_media(self.paths)
        return {
            "published": True,
            "projectId": self.project_id,
            "runId": self.run_id,
            "runStatus": self.run_status,
            "imported": self.created + self.reused,
            "created": self.created,
            "reused": self.reused,
            "stale": self.stale,
        }

    def close(self) -> None:
        if self.client is not None:
            self.client.__exit__(None, None, None)
            self.client = None


def publish_results(
    config: Config,
    summary: RunSummary,
    cases: list[PlanCase],
    paths: Paths,
    *,
    binding: BindingResult | None = None,
    classifications: dict[str, str] | None = None,
) -> dict[str, object]:
    session = PublishSession(config, cases, paths, binding=binding)
    started = session.start()
    if not started.get("started"):
        return {
            "published": False,
            "reason": started.get("reason", "publish did not start"),
            **({"mode": started["mode"]} if "mode" in started else {}),
            **({"blocked": started["blocked"]} if "blocked" in started else {}),
        }
    kinds = classifications or {}
    for result in summary.results:
        if not session.append(result, classification=kinds.get(result.test_id, "")):
            break
    return session.finish()


__all__ = ["PublishSession", "cleanup_transient_media", "publish_results"]
