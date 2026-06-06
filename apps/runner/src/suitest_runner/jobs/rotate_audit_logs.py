"""``rotate_audit_logs`` ARQ cron job — audit log archival + DB bloat guard (M4-32).

Runs daily (wired as a cron in :class:`~suitest_runner.worker.WorkerSettings`).
Audit rows older than ``SUITEST_AUDIT_LOG_RETENTION_DAYS`` (default 365) are
moved out of the hot ``audit_logs`` table into MinIO cold storage as one
gzip-compressed JSONL object per workspace per calendar month:

    s3://<archive-bucket>/audit/<workspace_id>/<YYYY-MM>.jsonl.gz

After a month's object is written successfully its rows are deleted from the DB,
so the hot table only ever holds the retention window. The optional restore
endpoint (``POST /audit/restore``) re-imports a month on demand.

Safety:

* A group is archived only when *all* its rows are older than the cutoff, so a
  still-accumulating current month is never half-archived.
* Upload happens before delete; a failed upload leaves the rows in place for the
  next run (idempotent — re-archiving a month overwrites the object, then the
  same rows delete).
* ``audit_logs`` is absent from ``AUDITED_TABLES`` so these deletes do not
  recursively emit audit rows.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import aioboto3
import structlog
from botocore.config import Config
from sqlalchemy import delete, func, select
from suitest_db.models.audit import AuditLog

from suitest_runner.settings import RunnerSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


def _archive_key(workspace_id: str, year_month: str) -> str:
    return f"audit/{workspace_id}/{year_month}.jsonl.gz"


def _row_to_dict(row: AuditLog) -> dict[str, object]:
    """Serialise one audit row to a JSON-safe dict (round-trips on restore)."""
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "user_id": str(row.user_id) if row.user_id is not None else None,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "metadata": row.metadata_json,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "created_at": row.created_at.isoformat(),
    }


async def rotate_audit_logs(ctx: dict[str, object]) -> dict[str, object]:
    """Archive + prune audit rows older than the retention window. Cron entrypoint."""
    factory = ctx.get("session_factory")
    settings = ctx.get("settings")
    if not callable(factory) or not isinstance(settings, RunnerSettings):
        return {"archived_months": 0, "error": "RUNNER_CTX_INVALID"}

    cutoff = datetime.now(UTC) - timedelta(days=settings.audit_log_retention_days)
    archived = 0
    rows_total = 0

    s3_session = aioboto3.Session()
    s3_config = Config(
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
        signature_version="s3v4",
    )

    async with (
        factory() as session,
        s3_session.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=s3_config,
        ) as client,
    ):
        # Group expired rows by (workspace, YYYY-MM). ``to_char`` keeps the
        # grouping in Postgres so we don't pull rows just to bucket them.
        month_expr = func.to_char(AuditLog.created_at, "YYYY-MM")
        groups = (
            await session.execute(
                select(AuditLog.workspace_id, month_expr)
                .where(AuditLog.created_at < cutoff)
                .group_by(AuditLog.workspace_id, month_expr)
            )
        ).all()

        for workspace_id, year_month in groups:
            rows = (
                (
                    await session.execute(
                        select(AuditLog)
                        .where(
                            AuditLog.workspace_id == workspace_id,
                            func.to_char(AuditLog.created_at, "YYYY-MM") == year_month,
                            AuditLog.created_at < cutoff,
                        )
                        .order_by(AuditLog.created_at)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                continue

            body = _serialise(rows)
            await client.put_object(
                Bucket=settings.s3_archive_bucket,
                Key=_archive_key(workspace_id, year_month),
                Body=body,
                ContentType="application/gzip",
            )
            ids = [r.id for r in rows]
            await session.execute(delete(AuditLog).where(AuditLog.id.in_(ids)))
            await session.commit()
            archived += 1
            rows_total += len(ids)
            log.info(
                "audit.rotate.archived",
                workspace_id=workspace_id,
                month=year_month,
                rows=len(ids),
            )

    log.info("audit.rotate.done", archived_months=archived, rows=rows_total)
    return {"archived_months": archived, "rows": rows_total}


def _serialise(rows: list[AuditLog]) -> bytes:
    """JSONL → gzip bytes for one month's audit rows."""
    lines = "\n".join(json.dumps(_row_to_dict(r), separators=(",", ":")) for r in rows)
    return gzip.compress(lines.encode("utf-8"))


async def restore_audit_logs(
    ctx: dict[str, object],
    workspace_id: str,
    year_month: str,
) -> dict[str, object]:
    """ARQ job: re-import one archived audit month. Enqueued by ``POST /audit/restore``."""
    factory = ctx.get("session_factory")
    settings = ctx.get("settings")
    if not callable(factory) or not isinstance(settings, RunnerSettings):
        return {"restored": 0, "error": "RUNNER_CTX_INVALID"}
    async with factory() as session:
        restored = await restore_audit_month(
            session, workspace_id=workspace_id, year_month=year_month, settings=settings
        )
    return {"restored": restored, "workspace_id": workspace_id, "month": year_month}


async def restore_audit_month(
    session: AsyncSession,
    *,
    workspace_id: str,
    year_month: str,
    settings: RunnerSettings,
) -> int:
    """Re-import an archived month back into the hot table. Returns rows restored.

    Used by the API ``POST /audit/restore`` endpoint. Idempotent: rows already
    present (same id) are skipped via ``ON CONFLICT DO NOTHING``.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    s3_session = aioboto3.Session()
    s3_config = Config(
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
        signature_version="s3v4",
    )
    async with s3_session.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=s3_config,
    ) as client:
        obj = await client.get_object(
            Bucket=settings.s3_archive_bucket,
            Key=_archive_key(workspace_id, year_month),
        )
        raw = await obj["Body"].read()

    decoded = gzip.decompress(raw).decode("utf-8")
    restored = 0
    for line in decoded.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        stmt = (
            pg_insert(AuditLog)
            .values(
                id=record["id"],
                workspace_id=record["workspace_id"],
                user_id=record["user_id"],
                action=record["action"],
                resource_type=record["resource_type"],
                resource_id=record["resource_id"],
                metadata_json=record["metadata"],
                ip_address=record["ip_address"],
                user_agent=record["user_agent"],
                created_at=record["created_at"],
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.execute(stmt)
        restored += 1
    await session.commit()
    return restored
