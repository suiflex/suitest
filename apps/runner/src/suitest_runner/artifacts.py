"""Artifact upload pipeline — M1c Task 13 lands the MinIO writer here.

For the Task 12 orchestrator we expose a no-op :func:`upload_artifacts` so the
import in :mod:`suitest_runner.jobs.run_test_case` resolves cleanly even when
S3-targeted artifacts haven't been wired yet. Task 13 replaces this stub with
the aioboto3-backed implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

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
    """Persist MCP artifacts to S3/MinIO + the ``artifacts`` table.

    Task 12 ships this as a no-op so the orchestrator's late import resolves.
    Task 13 replaces the body with the real aioboto3 upload + DB row writer.
    """
    pending = list(artifacts)
    if pending:
        log.info(
            "artifact.upload.deferred",
            run_id=run_id,
            count=len(pending),
            reason="m1c-task-13",
        )
