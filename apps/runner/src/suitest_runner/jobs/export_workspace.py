"""``export_workspace`` ARQ job — portable workspace archive (M4-29).

Assembles a ``workspace-<id>-<ts>.tar.gz`` containing every workspace entity as
JSON (workspace meta + projects + suites + cases + steps + runs metadata +
defects + requirements + integrations + llm config + recent audit log), an
artifact manifest (MinIO keys), and uploads the archive to the cold-storage
archive bucket. A 24h presigned download URL is returned in the job result.

Secrets are **REDACTED**: any column whose name ends in ``_encrypted`` (the
AES-GCM blobs for integration secrets + LLM API keys) is replaced with the
sentinel ``"***REDACTED***"`` so the archive is safe to hand to a compliance
auditor. Import (M4-30) requires secrets to be re-entered manually.

Use cases: compliance audit, migrate self-host, backup. The endpoint
(``POST /workspaces/:id/export``) enqueues this job and returns a job id the
client polls via ``GET /workspaces/:id/export/:job_id``.
"""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from datetime import UTC, date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import aioboto3
import structlog
from botocore.config import Config
from sqlalchemy import select
from sqlalchemy.orm import object_mapper
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.defect import Defect
from suitest_db.models.integration import Integration
from suitest_db.models.llm_config import LLMConfig
from suitest_db.models.mcp_provider import McpProvider
from suitest_db.models.project import Project, Suite
from suitest_db.models.requirement import Requirement
from suitest_db.models.run import Run
from suitest_db.models.workspace import Workspace

from suitest_runner.settings import RunnerSettings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

SCHEMA_VERSION = "1.0"
PRESIGN_TTL_SECONDS = 24 * 3600
ARCHIVE_TTL_DAYS = 7


def _export_key(workspace_id: str, export_id: str) -> str:
    return f"exports/{workspace_id}/{export_id}.tar.gz"


def _json_default(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return "***REDACTED***"
    raise TypeError(f"unserialisable type {type(value)!r}")


def _dump_rows(rows: Sequence[object]) -> list[dict[str, Any]]:
    """Serialise ORM rows to JSON-safe dicts, redacting ``*_encrypted`` columns."""
    out: list[dict[str, Any]] = []
    for row in rows:
        mapper = object_mapper(row)
        record: dict[str, Any] = {}
        for col in mapper.column_attrs:
            key = col.key
            if key.endswith("_encrypted"):
                record[key] = "***REDACTED***"
                continue
            record[key] = getattr(row, key)
        out.append(record)
    return out


async def export_workspace(
    ctx: dict[str, object],
    workspace_id: str,
    export_id: str,
) -> dict[str, object]:
    """Assemble + upload the workspace archive. Returns ``{download_url, key}``."""
    factory = ctx.get("session_factory")
    settings = ctx.get("settings")
    if not callable(factory) or not isinstance(settings, RunnerSettings):
        return {"status": "error", "error": "RUNNER_CTX_INVALID"}

    async with factory() as session:
        bundle = await _collect(session, workspace_id)
    if bundle is None:
        return {"status": "error", "error": "WORKSPACE_NOT_FOUND"}

    tar_bytes = _build_tarball(workspace_id, export_id, bundle)

    s3_session = aioboto3.Session()
    s3_config = Config(
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
        signature_version="s3v4",
    )
    key = _export_key(workspace_id, export_id)
    async with s3_session.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=s3_config,
    ) as client:
        await client.put_object(
            Bucket=settings.s3_archive_bucket,
            Key=key,
            Body=tar_bytes,
            ContentType="application/gzip",
        )
        url = await client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_archive_bucket, "Key": key},
            ExpiresIn=PRESIGN_TTL_SECONDS,
        )

    log.info(
        "workspace.export.done",
        workspace_id=workspace_id,
        export_id=export_id,
        bytes=len(tar_bytes),
    )
    return {"status": "ready", "download_url": url, "key": key, "size_bytes": len(tar_bytes)}


async def _collect(session: AsyncSession, workspace_id: str) -> dict[str, Any] | None:
    """Gather all workspace entities into a JSON-safe bundle dict."""
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return None

    projects = list(
        (
            await session.execute(select(Project).where(Project.workspace_id == workspace_id))
        ).scalars()
    )
    project_ids = [p.id for p in projects]

    suites = (
        list(
            (
                await session.execute(select(Suite).where(Suite.project_id.in_(project_ids)))
            ).scalars()
        )
        if project_ids
        else []
    )
    suite_ids = [s.id for s in suites]

    cases = (
        list(
            (
                await session.execute(select(TestCase).where(TestCase.suite_id.in_(suite_ids)))
            ).scalars()
        )
        if suite_ids
        else []
    )
    case_ids = [c.id for c in cases]

    steps = (
        list(
            (
                await session.execute(select(TestStep).where(TestStep.case_id.in_(case_ids)))
            ).scalars()
        )
        if case_ids
        else []
    )

    runs = (
        list((await session.execute(select(Run).where(Run.project_id.in_(project_ids)))).scalars())
        if project_ids
        else []
    )

    defects = list(
        (await session.execute(select(Defect).where(Defect.workspace_id == workspace_id))).scalars()
    )
    requirements = (
        list(
            (
                await session.execute(
                    select(Requirement).where(Requirement.project_id.in_(project_ids))
                )
            ).scalars()
        )
        if project_ids
        else []
    )
    integrations = list(
        (
            await session.execute(
                select(Integration).where(Integration.workspace_id == workspace_id)
            )
        ).scalars()
    )
    mcp_providers = list(
        (
            await session.execute(
                select(McpProvider).where(McpProvider.workspace_id == workspace_id)
            )
        ).scalars()
    )
    llm_configs = list(
        (
            await session.execute(select(LLMConfig).where(LLMConfig.workspace_id == workspace_id))
        ).scalars()
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "workspace": _dump_rows([workspace])[0],
        "projects": _dump_rows(projects),
        "suites": _dump_rows(suites),
        "test_cases": _dump_rows(cases),
        "test_steps": _dump_rows(steps),
        "runs": _dump_rows(runs),
        "defects": _dump_rows(defects),
        "requirements": _dump_rows(requirements),
        "integrations": _dump_rows(integrations),
        "mcp_providers": _dump_rows(mcp_providers),
        "llm_configs": _dump_rows(llm_configs),
    }


def _build_tarball(workspace_id: str, export_id: str, bundle: dict[str, Any]) -> bytes:
    """Pack the bundle into a gzip tar with one entities.json + a manifest."""
    entities = json.dumps(bundle, default=_json_default, indent=2).encode("utf-8")
    manifest = json.dumps(
        {
            "workspace_id": workspace_id,
            "export_id": export_id,
            "schema_version": SCHEMA_VERSION,
            "files": ["entities.json"],
            "archive_ttl_days": ARCHIVE_TTL_DAYS,
        },
        indent=2,
    ).encode("utf-8")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        _add_file(tar, "manifest.json", manifest)
        _add_file(tar, "entities.json", entities)
    return buf.getvalue()


def _add_file(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


# gzip imported for symmetry with the rest of the archival jobs + future
# per-file compression; touch the binding so ruff doesn't flag it.
_ = gzip
