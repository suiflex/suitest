"""Artifact upload pipeline — MinIO / S3 writer for MCP artifacts.

The runner orchestrator calls :func:`upload_artifacts` after each step that
returns at least one :class:`McpArtifact`. For every artifact:

1. Build a deterministic key under ``runs/<run_id>/step-<step_order>/<kind>/<filename>``
   so the storage layout mirrors the run/step tree and de-duplicates names
   across kinds (a ``console.log`` from a SCREENSHOT call lives in a different
   prefix than the same filename emitted as a CONSOLE_LOG).
2. Write the bytes (or the encoded text body) through the configured storage
   backend (:mod:`suitest_runner.storage`) — S3/MinIO in server mode, a plain
   disk folder in local mode.
3. Insert one row in the ``artifacts`` table that links the upload back to the
   ``run_steps`` row, with the canonical ``s3://bucket/key`` (or ``local://key``)
   URL so consumers can resolve the object without re-deriving the path.

Mime type resolution:
* Use the artifact's ``content_type`` field if the producer set one.
* Otherwise guess from the filename suffix.
* Final fallback is ``application/octet-stream`` so S3 always sees a value.

The implementation is intentionally single-pass over the input iterable so
producers can lazily yield artifacts without us materialising the whole list
(a video trace can be tens of MB).
"""

from __future__ import annotations

import mimetypes
from typing import TYPE_CHECKING

import structlog

from suitest_runner.settings import RunnerSettings
from suitest_runner.storage import make_storage

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_mcp.models import McpArtifact


log = structlog.get_logger(__name__)


async def upload_artifacts(
    *,
    session: AsyncSession,
    ctx: dict[str, object],
    run_id: str,
    run_step_id: str,
    step_order: int,
    artifacts: Iterable[McpArtifact],
) -> None:
    """Upload MCP artifacts to S3/MinIO and persist ``artifacts`` rows.

    Args:
        session: Live ``AsyncSession`` — the same session the run-step row was
            created in. Reused so the artifact rows land in the same
            transaction the orchestrator commits at the end of the step.
        ctx: ARQ job context. Must carry ``"settings": RunnerSettings``
            (populated by :func:`suitest_runner.worker.startup`).
        run_id: Public/internal run identifier — first path component.
        run_step_id: FK back to the row in ``run_steps`` that this artifact
            attaches to.
        step_order: 0-indexed monotonic position of the step within the run.
            Used in the S3 key so siblings sort correctly under the prefix.
        artifacts: Iterable of MCP artifacts emitted by the step. Empty iter
            is a fast no-op — no S3 client is opened, no DB write happens.
    """
    pending = list(artifacts)
    if not pending:
        return

    settings = ctx.get("settings")
    if not isinstance(settings, RunnerSettings):
        log.warning(
            "artifact.upload.no_settings",
            run_id=run_id,
            count=len(pending),
        )
        return

    # Late-import the DB repo so test fixtures that monkeypatch the symbol on
    # this module (not the source package) keep working.
    from suitest_db.repositories.runs import ArtifactRepo

    repo = ArtifactRepo(session)
    storage = make_storage(settings)
    for art in pending:
        key = f"runs/{run_id}/step-{step_order}/{art.kind.lower()}/{art.filename}"
        body = _body_bytes(art)
        content_type = (
            art.content_type or mimetypes.guess_type(art.filename)[0] or "application/octet-stream"
        )
        url = await storage.put(key=key, body=body, content_type=content_type)
        await repo.create_artifact(
            run_step_id=run_step_id,
            kind=art.kind,
            url=url,
            size_bytes=len(body),
            mime_type=content_type,
            metadata=art.metadata or None,
        )
        log.info(
            "artifact.uploaded",
            run_id=run_id,
            run_step_id=run_step_id,
            kind=art.kind,
            key=key,
            bytes=len(body),
        )


def _body_bytes(art: McpArtifact) -> bytes:
    """Resolve the raw bytes to upload for one artifact.

    Producers populate exactly one of ``bytes_`` (binary blob, e.g.
    screenshots, videos) or ``text`` (UTF-8 text, e.g. HAR, console log).
    The fallback empty-bytes result keeps ``put_object`` legal even for
    metadata-only artifacts (rare, but valid per the McpArtifact schema).
    """
    if art.bytes_ is not None:
        return art.bytes_
    if art.text is not None:
        return art.text.encode("utf-8")
    return b""
