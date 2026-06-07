"""WorkspacePromptOverride repository (M5-3).

Manages per-workspace prompt forks: creating a fork auto-increments
``fork_version`` and makes the new row the single active override for its
``(workspace_id, prompt_name)``; :meth:`get_active` is what the prompt resolver
calls to decide whether a workspace overrides the file default.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import func, select, update
from suitest_db.models.workspace_prompt_override import WorkspacePromptOverride
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class WorkspacePromptOverrideCreate(BaseModel):
    workspace_id: str
    prompt_name: str
    base_version: str
    fork_version: int
    content: str
    hash: str
    label: str | None = None
    is_active: bool = False
    created_by: uuid.UUID | None = None


class WorkspacePromptOverrideUpdate(BaseModel):
    is_active: bool | None = None
    label: str | None = None


class WorkspacePromptOverrideRepo(
    AsyncRepository[
        WorkspacePromptOverride,
        WorkspacePromptOverrideCreate,
        WorkspacePromptOverrideUpdate,
    ]
):
    model = WorkspacePromptOverride

    async def get_active(
        self, workspace_id: str, prompt_name: str
    ) -> WorkspacePromptOverride | None:
        stmt = select(WorkspacePromptOverride).where(
            WorkspacePromptOverride.workspace_id == workspace_id,
            WorkspacePromptOverride.prompt_name == prompt_name,
            WorkspacePromptOverride.is_active.is_(True),
        )
        row: WorkspacePromptOverride | None = await self.session.scalar(stmt)
        return row

    async def list_for_workspace(
        self, workspace_id: str, *, prompt_name: str | None = None
    ) -> Sequence[WorkspacePromptOverride]:
        stmt = select(WorkspacePromptOverride).where(
            WorkspacePromptOverride.workspace_id == workspace_id
        )
        if prompt_name is not None:
            stmt = stmt.where(WorkspacePromptOverride.prompt_name == prompt_name)
        stmt = stmt.order_by(
            WorkspacePromptOverride.prompt_name.asc(),
            WorkspacePromptOverride.fork_version.desc(),
        )
        return (await self.session.scalars(stmt)).all()

    async def _next_fork_version(self, workspace_id: str, prompt_name: str) -> int:
        stmt = select(func.max(WorkspacePromptOverride.fork_version)).where(
            WorkspacePromptOverride.workspace_id == workspace_id,
            WorkspacePromptOverride.prompt_name == prompt_name,
        )
        current = await self.session.scalar(stmt)
        return int(current or 0) + 1

    async def _deactivate_all(self, workspace_id: str, prompt_name: str) -> None:
        await self.session.execute(
            update(WorkspacePromptOverride)
            .where(
                WorkspacePromptOverride.workspace_id == workspace_id,
                WorkspacePromptOverride.prompt_name == prompt_name,
            )
            .values(is_active=False)
        )

    async def create_fork(
        self,
        *,
        workspace_id: str,
        prompt_name: str,
        base_version: str,
        content: str,
        content_hash: str,
        label: str | None,
        created_by: uuid.UUID | None,
        activate: bool = True,
    ) -> WorkspacePromptOverride:
        """Insert a new fork; when ``activate`` it becomes the sole active override."""
        fork_version = await self._next_fork_version(workspace_id, prompt_name)
        if activate:
            await self._deactivate_all(workspace_id, prompt_name)
        row = WorkspacePromptOverride(
            workspace_id=workspace_id,
            prompt_name=prompt_name,
            base_version=base_version,
            fork_version=fork_version,
            content=content,
            hash=content_hash,
            label=label,
            is_active=activate,
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def activate(self, workspace_id: str, override_id: str) -> WorkspacePromptOverride | None:
        """Make ``override_id`` the active fork for its prompt (deactivating siblings)."""
        row = await self.get_by_id(override_id)
        if row is None or row.workspace_id != workspace_id:
            return None
        await self._deactivate_all(workspace_id, row.prompt_name)
        row.is_active = True
        await self.session.flush()
        return row
