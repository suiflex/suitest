"""Variable & Secret management service with hierarchical resolution."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.variables import (
    SuiteVariableCreate,
    SuiteVariableRepo,
    SuiteVariableUpdate,
    WorkspaceVariableCreate,
    WorkspaceVariableRepo,
    WorkspaceVariableUpdate,
)

from suitest_api.schemas.variable import (
    ResolvedVariableItem,
    VariableCreate,
    VariablePublic,
    VariableUpdate,
)


class VariableService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._ws_repo = WorkspaceVariableRepo(session)
        self._suite_repo = SuiteVariableRepo(session)

    # --- Workspace Variables -----------------------------------------------

    async def list_workspace_variables(self, workspace_id: str) -> list[VariablePublic]:
        rows = await self._ws_repo.list_by_workspace(workspace_id)
        return [
            VariablePublic(
                id=r.id,
                key=r.key,
                is_secret=r.is_secret,
                value=None if r.is_secret else r.value,
                has_value=bool(r.value),
                description=r.description,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    async def create_workspace_variable(
        self, workspace_id: str, dto: VariableCreate
    ) -> VariablePublic:
        row = await self._ws_repo.create(
            WorkspaceVariableCreate(
                workspace_id=workspace_id,
                key=dto.key,
                value=dto.value,
                is_secret=dto.is_secret,
                description=dto.description,
            )
        )
        await self._session.refresh(row)
        return VariablePublic(
            id=row.id,
            key=row.key,
            is_secret=row.is_secret,
            value=None if row.is_secret else row.value,
            has_value=bool(row.value),
            description=row.description,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def update_workspace_variable(
        self, workspace_id: str, var_id: str, dto: VariableUpdate
    ) -> VariablePublic | None:
        row = await self._ws_repo.get_by_id(var_id)
        if row is None or row.workspace_id != workspace_id:
            return None

        update_dto = WorkspaceVariableUpdate(
            key=dto.key,
            value=dto.value,
            is_secret=dto.is_secret,
            description=dto.description,
        )
        updated = await self._ws_repo.update(var_id, update_dto)
        if updated is None:
            return None

        await self._session.refresh(updated)

        return VariablePublic(
            id=updated.id,
            key=updated.key,
            is_secret=updated.is_secret,
            value=None if updated.is_secret else updated.value,
            has_value=bool(updated.value),
            description=updated.description,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
        )

    async def delete_workspace_variable(self, workspace_id: str, var_id: str) -> bool:
        row = await self._ws_repo.get_by_id(var_id)
        if row is None or row.workspace_id != workspace_id:
            return False
        return await self._ws_repo.delete(var_id)

    # --- Suite Variables ---------------------------------------------------

    async def list_suite_variables(self, suite_id: str) -> list[VariablePublic]:
        rows = await self._suite_repo.list_by_suite(suite_id)
        return [
            VariablePublic(
                id=r.id,
                key=r.key,
                is_secret=r.is_secret,
                value=None if r.is_secret else r.value,
                has_value=bool(r.value),
                description=r.description,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    async def create_suite_variable(self, suite_id: str, dto: VariableCreate) -> VariablePublic:
        row = await self._suite_repo.create(
            SuiteVariableCreate(
                suite_id=suite_id,
                key=dto.key,
                value=dto.value,
                is_secret=dto.is_secret,
                description=dto.description,
            )
        )
        await self._session.refresh(row)
        return VariablePublic(
            id=row.id,
            key=row.key,
            is_secret=row.is_secret,
            value=None if row.is_secret else row.value,
            has_value=bool(row.value),
            description=row.description,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def update_suite_variable(
        self, suite_id: str, var_id: str, dto: VariableUpdate
    ) -> VariablePublic | None:
        row = await self._suite_repo.get_by_id(var_id)
        if row is None or row.suite_id != suite_id:
            return None

        update_dto = SuiteVariableUpdate(
            key=dto.key,
            value=dto.value,
            is_secret=dto.is_secret,
            description=dto.description,
        )
        updated = await self._suite_repo.update(var_id, update_dto)
        if updated is None:
            return None

        await self._session.refresh(updated)

        return VariablePublic(
            id=updated.id,
            key=updated.key,
            is_secret=updated.is_secret,
            value=None if updated.is_secret else updated.value,
            has_value=bool(updated.value),
            description=updated.description,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
        )

    async def delete_suite_variable(self, suite_id: str, var_id: str) -> bool:
        row = await self._suite_repo.get_by_id(var_id)
        if row is None or row.suite_id != suite_id:
            return False
        return await self._suite_repo.delete(var_id)

    # --- Hierarchical Resolution -------------------------------------------

    async def resolve_hierarchy(
        self,
        workspace_id: str,
        suite_id: str | None = None,
        *,
        include_secrets: bool = False,
    ) -> list[ResolvedVariableItem]:
        """Resolve workspace + suite variables. Suite variables take precedence."""
        resolved: dict[str, ResolvedVariableItem] = {}

        # 1. Base workspace variables
        ws_vars = await self._ws_repo.list_by_workspace(workspace_id)
        for w in ws_vars:
            resolved[w.key] = ResolvedVariableItem(
                key=w.key,
                value=w.value if (not w.is_secret or include_secrets) else None,
                is_secret=w.is_secret,
                has_value=bool(w.value),
                source_scope="workspace",
                source_id=workspace_id,
                description=w.description,
            )

        # 2. Suite overrides
        if suite_id is not None:
            suite_vars = await self._suite_repo.list_by_suite(suite_id)
            for s in suite_vars:
                resolved[s.key] = ResolvedVariableItem(
                    key=s.key,
                    value=s.value if (not s.is_secret or include_secrets) else None,
                    is_secret=s.is_secret,
                    has_value=bool(s.value),
                    source_scope="suite",
                    source_id=suite_id,
                    description=s.description,
                )

        return list(resolved.values())
