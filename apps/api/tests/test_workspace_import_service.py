"""Tests for WorkspaceImportService archive parsing + FK remap (M4-30).

The full DB round-trip is covered by the API integration suite; here we cover
schema validation, archive parsing failures, and the id-remap logic via a fake
session that records ``add`` calls (no DB needed).
"""

from __future__ import annotations

import io
import json
import tarfile

import pytest
from suitest_api.services.workspace_import_service import (
    SUPPORTED_SCHEMA,
    WorkspaceImportError,
    WorkspaceImportService,
    _read_bundle,
)
from suitest_db.models.project import Project, Suite


def _archive(bundle: dict[str, object]) -> bytes:
    entities = json.dumps(bundle).encode("utf-8")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("entities.json")
        info.size = len(entities)
        tar.addfile(info, io.BytesIO(entities))
    return buf.getvalue()


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)


def test_read_bundle_rejects_non_tar() -> None:
    with pytest.raises(WorkspaceImportError):
        _read_bundle(b"not a tarball")


def test_read_bundle_parses_entities() -> None:
    bundle = _read_bundle(_archive({"schema_version": SUPPORTED_SCHEMA, "projects": []}))
    assert bundle["schema_version"] == SUPPORTED_SCHEMA


def test_restore_remaps_parent_fks() -> None:
    svc = WorkspaceImportService(_FakeSession(), user_id="00000000-0000-0000-0000-000000000001")  # type: ignore[arg-type]
    proj_rows = [{"id": "old_p1", "workspace_id": "old_ws", "slug": "web", "name": "Web"}]
    proj_map = svc._restore(Project, proj_rows, {"workspace_id": "new_ws"})
    assert len(proj_map) == 1
    new_pid = proj_map["old_p1"]

    suite_rows = [{"id": "old_s1", "project_id": "old_p1", "slug": "smoke", "name": "Smoke"}]
    suite_map = svc._restore(Suite, suite_rows, {"project_id": proj_map})
    assert len(suite_map) == 1
    # the created Suite points at the remapped project id
    created_suites = [o for o in svc._session.added if isinstance(o, Suite)]  # type: ignore[attr-defined]
    assert created_suites[0].project_id == new_pid


def test_restore_skips_orphan_rows() -> None:
    svc = WorkspaceImportService(_FakeSession(), user_id="00000000-0000-0000-0000-000000000001")  # type: ignore[arg-type]
    # suite references a project id not present in the (empty) map → skipped
    suite_map = svc._restore(
        Suite, [{"id": "s1", "project_id": "missing", "name": "X", "slug": "x"}], {"project_id": {}}
    )
    assert suite_map == {}
