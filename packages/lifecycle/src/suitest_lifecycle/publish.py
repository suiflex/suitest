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
import re
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
_CREDENTIAL_REPLACEMENTS = {
    "USERNAME": 'USERNAME = os.environ.get("SUITEST_TEST_USERNAME", "")\n',
    "PASSWORD": 'PASSWORD = os.environ.get("SUITEST_TEST_PASSWORD", "")\n',
}

# PlanCase.title is the generated test function slug (codegen emits
# ``test_<title>``), so the publish layer is where the human display title is
# minted: ``slug`` carries the technical key, ``title`` the readable sentence.
# Mirrors suitest_shared.text.humanize_slug (lifecycle stays stdlib-only).
_ACRONYMS = frozenset({"api", "url", "id", "ui", "ux", "http", "sql", "ok", "sso", "mcp"})


def _humanize(slug: str) -> str:
    words = list(filter(None, re.split(r"[-_\s]+", slug.strip())))
    if not words:
        return slug.strip()
    first, *rest = words
    head = first.upper() if first.lower() in _ACRONYMS else first.capitalize()
    tail = [word.upper() if word.lower() in _ACRONYMS else word.lower() for word in rest]
    return " ".join((head, *tail))


def _suite_name(config: Config) -> str:
    return config.publish.suite_name or f"{config.project_name} {config.mode.value}"


def _sanitize_automation_code(code: str) -> str:
    """Prevent credentials embedded by pre-fix generators from entering the DB."""
    lines = code.splitlines(keepends=True)
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if "os.environ" in stripped:
            continue
        name = stripped.partition(" ")[0]
        replacement = _CREDENTIAL_REPLACEMENTS.get(name)
        if replacement is not None and stripped.startswith(f"{name} ="):
            lines[index] = replacement
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
                "testingApproach": c.testing_approach.value,
                "testLevel": c.test_level.value,
                "framework": c.framework or None,
                "strategyRef": c.strategy_ref or None,
                "steps": _case_step_payloads(c),
            }
        )
    return out


def _case_step_payloads(case: PlanCase) -> list[dict[str, object]]:
    return [
        {
            "order": index + 1,
            "action": step.description,
            "expected": step.description if step.type == "assertion" else "",
            "code": None,
        }
        for index, step in enumerate(case.steps)
    ]


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


def _unlink_matches(root: Path, pattern: str) -> None:
    for candidate in root.rglob(pattern):
        _unlink(str(candidate))


def _deepest_directories(root: Path) -> list[Path]:
    directories = [candidate for candidate in root.rglob("*") if candidate.is_dir()]
    directories.sort(key=lambda path: len(path.parts), reverse=True)
    return directories


def _remove_empty_directories(root: Path) -> None:
    for directory in _deepest_directories(root):
        with suppress(OSError):
            directory.rmdir()


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
                _unlink_matches(video_dir, "*.webm")
                _remove_empty_directories(video_dir)
                with suppress(OSError):
                    video_dir.rmdir()
        except OSError:
            pass

    # Per-step PNGs are deliberately KEPT. The ``<TC>.result.json`` sidecar keeps
    # pointing at them, and every later sidecar-based publish (blackbox
    # compatibility path, re-publish of an unchanged run) re-uploads from those
    # files. Deleting them made the second publish ship steps with no evidence,
    # which silently blanked the web preview and the UAT PDF Evidence column.
    # They are small (tens of KB) and the next run overwrites the same names.

    # The final screenshot is not published because the final recorded step is
    # already the preview. It is safe to discard once this result committed.
    _unlink(result.screenshot_path)


def cleanup_transient_media(paths: Paths) -> None:
    """Remove ephemeral browser media after a fully successful publish."""
    if not paths.tmp_dir.is_dir():
        return
    # PNGs stay: they are the evidence a later sidecar-based publish re-uploads.
    _unlink_matches(paths.tmp_dir, "*.webm")
    _unlink_matches(paths.tmp_dir, "*.zip")
    # Bottom-up empty-dir removal; JSON/report files remain untouched.
    _remove_empty_directories(paths.tmp_dir)


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

    def finish(self, *, coverage: dict[str, object] | None = None) -> dict[str, object]:
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
            coverage_payload = coverage
            coverage_file = self.config.testing.coverage_file
            coverage_path = Path(coverage_file)
            if coverage_file and not coverage_path.is_absolute():
                coverage_path = self.config.project_path / coverage_path
            if not coverage_file:
                coverage_path = self.paths.coverage_json
            if coverage_path.is_file():
                coverage_payload = {
                    **(coverage or {}),
                    "artifactUrl": self.client.upload_file(
                        str(coverage_path), content_type="application/json"
                    ),
                }
            run = self.client.ingest_run(
                run_id=self.run_id,
                finalize=True,
                project_id=self.project_id,
                suite_name=_suite_name(self.config),
                name=f"{self.config.project_name} lifecycle",
                results=[],
                coverage_summary=coverage_payload,
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
    return session.finish(coverage=summary.coverage)


__all__ = ["PublishSession", "cleanup_transient_media", "publish_results"]
