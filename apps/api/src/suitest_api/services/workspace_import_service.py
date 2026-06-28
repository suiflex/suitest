"""WorkspaceImportService — restore/clone a workspace from an export archive (M4-30).

Counterpart to the M4-29 export job. Accepts the ``workspace-*.tar.gz`` produced
by ``export_workspace`` and reconstructs the *structural test assets* into a
brand-new workspace owned by the importing user:

    projects → suites → test_cases → test_steps → requirements

Deliberately NOT imported (operational / sensitive data):

* runs / defects — runtime history is environment-specific; a fresh workspace
  starts clean.
* integrations / llm config / mcp providers — these carry secrets that the
  export REDACTED, so they must be re-entered manually (spec requirement).

Safety:

* Schema-version compatibility is checked against :data:`SUPPORTED_SCHEMA` — a
  mismatch is a 400, never a partial import.
* New ids are minted for every row; parent FKs are remapped through an id-map so
  the imported tree is internally consistent and collision-free.
* Rows are deduped by ``public_id`` within each table so a malformed archive
  with duplicates can't violate a uniqueness constraint mid-import.
"""

from __future__ import annotations

import io
import json
import tarfile
from typing import TYPE_CHECKING, Any
from uuid import UUID

from suitest_db.ids import new_id
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_db.models.requirement import Requirement
from suitest_db.models.tenancy import Membership
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SUPPORTED_SCHEMA = "1.0"

# Columns never copied verbatim: server-managed, identity, or secret.
_SKIP_COLUMNS = frozenset({"id", "created_at", "updated_at", "deleted_at"})


class WorkspaceImportError(Exception):
    """Raised on an unreadable / incompatible archive (→ HTTP 400)."""


class WorkspaceImportService:
    """Reconstruct a workspace tree from an export archive into a new workspace."""

    def __init__(self, session: AsyncSession, *, user_id: str) -> None:
        self._session = session
        self._user_id = user_id

    async def import_archive(self, tar_bytes: bytes) -> Workspace:
        """Parse + validate the archive and create a new workspace. Returns it."""
        bundle = _read_bundle(tar_bytes)
        schema = str(bundle.get("schema_version", ""))
        if schema != SUPPORTED_SCHEMA:
            raise WorkspaceImportError(
                f"unsupported schema_version {schema!r} (expected {SUPPORTED_SCHEMA})"
            )

        ws_meta = bundle.get("workspace") or {}
        workspace = Workspace(
            id=new_id(),
            slug=f"imported-{new_id()[:8]}",
            name=f"{ws_meta.get('name', 'Imported workspace')} (imported)",
            region=str(ws_meta.get("region", "ap-southeast-1")),
        )
        self._session.add(workspace)
        self._session.add(
            Membership(
                workspace_id=workspace.id,
                user_id=UUID(self._user_id),
                role=Role.OWNER,
            )
        )
        await self._session.flush()

        proj_map = self._restore(
            Project, bundle.get("projects", []), {"workspace_id": workspace.id}
        )
        suite_map = self._restore(Suite, bundle.get("suites", []), {"project_id": proj_map})
        case_map = self._restore(
            TestCase,
            bundle.get("test_cases", []),
            {"suite_id": suite_map, "workspace_id": workspace.id},
        )
        self._restore(TestStep, bundle.get("test_steps", []), {"case_id": case_map})
        self._restore(Requirement, bundle.get("requirements", []), {"project_id": proj_map})

        await self._session.flush()
        return workspace

    def _restore(
        self,
        model: type[object],
        rows: list[dict[str, Any]],
        fk_remap: dict[str, str | dict[str, str]],
    ) -> dict[str, str]:
        """Insert ``rows`` as ``model`` with new ids + remapped FKs. Returns old→new id map.

        ``fk_remap`` maps a column name to either a literal value (e.g. the new
        workspace id) or an id-map dict (old parent id → new parent id). A row
        whose parent id is absent from its map is skipped (orphan).
        """
        columns = {c.key for c in model.__table__.columns}  # type: ignore[attr-defined]
        id_map: dict[str, str] = {}
        seen_public: set[str] = set()
        for raw in rows:
            old_id = str(raw.get("id", ""))
            public_id = raw.get("public_id")
            if isinstance(public_id, str):
                if public_id in seen_public:
                    continue
                seen_public.add(public_id)

            kwargs: dict[str, Any] = {}
            skip_row = False
            for key, value in raw.items():
                if key in _SKIP_COLUMNS or key.endswith("_encrypted") or key not in columns:
                    continue
                if key in fk_remap:
                    target = fk_remap[key]
                    if isinstance(target, dict):
                        mapped = target.get(str(value))
                        if mapped is None:
                            skip_row = True
                            break
                        kwargs[key] = mapped
                    else:
                        kwargs[key] = target
                    continue
                # Drop dangling cross-refs we are not importing (e.g. a project's
                # gating_suite_id resolved later) — null them out.
                if key.endswith("_id") and key not in columns:
                    continue
                kwargs[key] = value
            if skip_row:
                continue
            # Apply literal fk_remap values (e.g. the new workspace id) even when
            # the archive row lacks the column — old archives predate
            # ``test_cases.workspace_id`` (blocker #3), so it must be forced here.
            for remap_key, remap_target in fk_remap.items():
                if not isinstance(remap_target, dict) and remap_key not in kwargs:
                    kwargs[remap_key] = remap_target
            new_row_id = new_id()
            kwargs["id"] = new_row_id
            # Null out intra-table forward refs we can't guarantee yet.
            if "gating_suite_id" in kwargs:
                kwargs["gating_suite_id"] = None
            self._session.add(model(**kwargs))
            if old_id:
                id_map[old_id] = new_row_id
        return id_map


def _read_bundle(tar_bytes: bytes) -> dict[str, Any]:
    """Extract + parse ``entities.json`` from the gz tar archive."""
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            member = tar.extractfile("entities.json")
            if member is None:
                raise WorkspaceImportError("archive missing entities.json")
            data = member.read()
    except tarfile.TarError as exc:
        raise WorkspaceImportError(f"unreadable archive: {exc}") from exc
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        raise WorkspaceImportError(f"malformed entities.json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise WorkspaceImportError("entities.json is not an object")
    return parsed
