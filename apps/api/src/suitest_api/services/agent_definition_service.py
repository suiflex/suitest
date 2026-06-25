"""AgentDefinitionService — load, validate, and store workspace agent definitions (M8).

Business rules:
- YAML is validated against AgentPluginSpec before persisting.
- Duplicate active name within a workspace → DuplicateAgentDefinitionError (→ 409).
- Deactivation is soft (is_active=False); history is preserved for audit.
- All mutations emit an explicit write_audit row.
- The service is ZERO-tier-compatible: registering/listing definitions requires no LLM.
  Individual agents may declare requires_tier; enforcement is at invocation time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError
from suitest_agent.plugin_sdk.base import AgentPluginSpec
from suitest_db.audit import write_audit
from suitest_db.repositories.agent_definitions import (
    AgentDefinitionCreate,
    AgentDefinitionRepo,
)

from suitest_api.deps.tier import require_tier

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.agent_definition import AgentDefinition


class DuplicateAgentDefinitionError(Exception):
    """Raised when an active definition with the same name already exists."""

    def __init__(self, name: str) -> None:
        super().__init__(f"active agent definition {name!r} already exists in this workspace")
        self.name = name


class AgentSpecValidationError(Exception):
    """Raised when the submitted YAML cannot be parsed as a valid AgentPluginSpec."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class AgentDefinitionService:
    """Service for CRUD operations on workspace agent plugin definitions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AgentDefinitionRepo(session)

    @require_tier()  # ZERO-compatible — no LLM needed to store definitions
    async def list_definitions(self, workspace_id: str) -> list[AgentDefinition]:
        """Return all active definitions for the workspace, newest first."""
        rows = await self._repo.list_active(workspace_id)
        return list(rows)

    @require_tier()
    async def get_definition(self, workspace_id: str, name: str) -> AgentDefinition | None:
        """Return the active definition for ``name``, or ``None``."""
        return await self._repo.get_active_by_name(workspace_id, name)

    @require_tier()
    async def register_definition(
        self,
        *,
        workspace_id: str,
        spec_yaml: str,
        user_id: uuid.UUID | None,
    ) -> AgentDefinition:
        """Validate the YAML spec and insert a new agent definition row.

        Raises:
            AgentSpecValidationError: YAML is invalid or fails AgentPluginSpec validation.
            DuplicateAgentDefinitionError: An active definition with the same name exists.
        """
        spec = _parse_spec(spec_yaml)
        existing = await self._repo.get_active_by_name(workspace_id, spec.name)
        if existing is not None:
            raise DuplicateAgentDefinitionError(spec.name)

        dto = AgentDefinitionCreate(
            workspace_id=workspace_id,
            name=spec.name,
            spec_yaml=spec_yaml,
            spec_version=spec.version,
            created_by=str(user_id) if user_id is not None else None,
        )
        row = await self._repo.create(dto)
        await write_audit(
            self._session,
            workspace_id=workspace_id,
            user_id=str(user_id) if user_id is not None else None,
            action="insert",
            resource_type="agent_definition",
            resource_id=row.id,
            metadata={"name": spec.name, "version": spec.version},
        )
        return row

    @require_tier()
    async def update_definition(
        self,
        *,
        workspace_id: str,
        name: str,
        spec_yaml: str,
        user_id: uuid.UUID | None,
    ) -> AgentDefinition:
        """Replace the YAML spec of an existing active definition.

        Raises:
            AgentSpecValidationError: New YAML fails validation.
            KeyError: No active definition with ``name`` found.
        """
        spec = _parse_spec(spec_yaml)
        row = await self._repo.update_spec(workspace_id, name, spec_yaml, spec.version)
        if row is None:
            raise KeyError(f"agent definition {name!r} not found in workspace")
        await write_audit(
            self._session,
            workspace_id=workspace_id,
            user_id=str(user_id) if user_id is not None else None,
            action="update",
            resource_type="agent_definition",
            resource_id=row.id,
            metadata={"name": name, "new_version": spec.version},
        )
        return row

    @require_tier()
    async def deactivate_definition(
        self,
        *,
        workspace_id: str,
        name: str,
        user_id: uuid.UUID | None,
    ) -> bool:
        """Soft-delete an active definition.

        Returns ``True`` iff a row was deactivated, ``False`` if not found.
        """
        row = await self._repo.get_active_by_name(workspace_id, name)
        if row is None:
            return False
        deactivated = await self._repo.deactivate(workspace_id, name)
        if deactivated:
            await write_audit(
                self._session,
                workspace_id=workspace_id,
                user_id=str(user_id) if user_id is not None else None,
                action="delete",
                resource_type="agent_definition",
                resource_id=row.id,
                metadata={"name": name},
            )
        return deactivated


def _parse_spec(spec_yaml: str) -> AgentPluginSpec:
    """Parse and validate raw YAML into an AgentPluginSpec.

    Raises AgentSpecValidationError on any parse or validation failure.
    """
    try:
        data = yaml.safe_load(spec_yaml)
    except yaml.YAMLError as exc:
        raise AgentSpecValidationError(f"invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise AgentSpecValidationError("YAML must be a mapping (dict), not a list or scalar")

    try:
        return AgentPluginSpec.model_validate(data)
    except ValidationError as exc:
        raise AgentSpecValidationError(str(exc)) from exc
