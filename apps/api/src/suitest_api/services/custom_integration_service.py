"""Custom integration adapter layer (M9-3).

Defines the :class:`CustomIntegrationAdapterBase` Protocol and stub
implementations for Asana and ClickUp.

Real implementations would call the vendor REST APIs; these stubs log the
call and return mock data so the plugin contract is validated without
external dependencies.

Lookup is via :attr:`kind` (e.g. ``"asana"``, ``"clickup"``) in the
module-level :data:`CUSTOM_INTEGRATION_ADAPTERS` dict.

Usage::

    from suitest_api.services.custom_integration_service import (
        CUSTOM_INTEGRATION_ADAPTERS,
    )

    adapter = CUSTOM_INTEGRATION_ADAPTERS["asana"]
    url = await adapter.create_issue(
        defect_id="...", title="...", description="...", config={...}
    )
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import structlog

log = structlog.get_logger(__name__)


@runtime_checkable
class CustomIntegrationAdapterBase(Protocol):
    """Protocol every custom integration adapter must satisfy.

    Adapters are stateless: all per-call context (credentials, workspace,
    project ID, etc.) arrives via ``config``.
    """

    kind: str

    async def create_issue(
        self,
        defect_id: str,
        title: str,
        description: str,
        config: dict[str, str],
    ) -> str:
        """Create an issue in the external tracker.

        :param defect_id: Suitest defect ID (for cross-referencing).
        :param title: Issue title.
        :param description: Issue body / description.
        :param config: Adapter-specific config (base_url, token, project, etc.).
        :returns: External issue URL.
        """
        ...

    async def update_status(
        self,
        external_id: str,
        status: str,
        config: dict[str, str],
    ) -> None:
        """Update the status of an existing external issue.

        :param external_id: ID of the issue in the external system.
        :param status: New status string (adapter-defined semantics).
        :param config: Adapter-specific config.
        """
        ...

    async def health_check(self, config: dict[str, str]) -> bool:
        """Verify connectivity to the external system.

        :returns: ``True`` when the system is reachable and credentials are valid.
        """
        ...


class AsanaAdapter:
    """Stub Asana integration adapter (M9-3).

    Production implementation would use the Asana REST API
    ``POST /tasks`` to create issues and ``PUT /tasks/{task_gid}``
    to update status.
    """

    kind = "asana"

    async def create_issue(
        self,
        defect_id: str,
        title: str,
        description: str,
        config: dict[str, str],
    ) -> str:
        log.info(
            "asana_adapter.create_issue",
            defect_id=defect_id,
            title=title,
            stub=True,
        )
        project = config.get("project", "default-project")
        fake_gid = f"asana-{defect_id[:8]}"
        return f"https://app.asana.com/0/{project}/{fake_gid}"

    async def update_status(
        self,
        external_id: str,
        status: str,
        config: dict[str, str],
    ) -> None:
        log.info(
            "asana_adapter.update_status",
            external_id=external_id,
            status=status,
            stub=True,
        )

    async def health_check(self, config: dict[str, str]) -> bool:
        log.info("asana_adapter.health_check", stub=True)
        return True


class ClickUpAdapter:
    """Stub ClickUp integration adapter (M9-3).

    Production implementation would use the ClickUp REST API
    ``POST /list/{list_id}/task`` to create issues and
    ``PUT /task/{task_id}`` to update status.
    """

    kind = "clickup"

    async def create_issue(
        self,
        defect_id: str,
        title: str,
        description: str,
        config: dict[str, str],
    ) -> str:
        log.info(
            "clickup_adapter.create_issue",
            defect_id=defect_id,
            title=title,
            stub=True,
        )
        list_id = config.get("list_id", "default-list")
        fake_task_id = f"cu-{defect_id[:8]}"
        return f"https://app.clickup.com/t/{list_id}/{fake_task_id}"

    async def update_status(
        self,
        external_id: str,
        status: str,
        config: dict[str, str],
    ) -> None:
        log.info(
            "clickup_adapter.update_status",
            external_id=external_id,
            status=status,
            stub=True,
        )

    async def health_check(self, config: dict[str, str]) -> bool:
        log.info("clickup_adapter.health_check", stub=True)
        return True


# Module-level adapter map — pre-populated with the bundled stub adapters,
# keyed by :attr:`CustomIntegrationAdapterBase.kind`.
CUSTOM_INTEGRATION_ADAPTERS: dict[str, CustomIntegrationAdapterBase] = {
    adapter.kind: adapter for adapter in (AsanaAdapter(), ClickUpAdapter())
}
