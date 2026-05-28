"""Public-ID generation: Postgres function wrapper + SQLAlchemy event listeners.

The DB-side ``generate_public_id(prefix, workspace_id)`` plpgsql function
(installed by Alembic revision ``0014_public_id_function``) lazily creates one
``pubid_<workspace>_<prefix>`` sequence per (workspace, prefix) pair and returns
``prefix || '-' || nextval`` — see docs/DATA_MODEL.md §8.

This module:

1. Exposes :func:`generate_public_id` — an async helper that lets services /
   seed scripts call the function directly when they need a public ID outside
   of an ``INSERT`` (e.g. preview UI, dry-runs).
2. Registers ``before_insert`` listeners for :class:`TestCase`, :class:`Run`,
   :class:`Requirement`, and :class:`Defect` that fill ``public_id`` from the
   transient attribute ``_workspace_id_for_pubid`` the repo layer sets just
   before flushing. The listener is **idempotent**: a pre-set ``public_id``
   is left alone (so seeders / migrations can pin specific IDs).

The transient ``_workspace_id_for_pubid`` is **not** a mapped column — it is a
plain Python attribute on the instance carrying the workspace context the
listener needs (since the listener has no access to the request's
ContextVar). To keep mypy strict happy without polluting the ORM models with
a non-mapped Mapped[...] declaration, callers use :func:`set_workspace_id` to
attach it and the listener reads it back via :func:`_get_workspace_id`.

Side-effect import: ``suitest_db/__init__.py`` imports this module so the four
``@event.listens_for(..., "before_insert")`` decorators run at package import
time. Without that import the listeners would never attach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import event, text

from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect
from suitest_db.models.requirement import Requirement
from suitest_db.models.run import Run

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Mapper


# --- prefix map (docs/DATA_MODEL.md §8) ---------------------------------------

_TC_PREFIX = "TC"
_RUN_PREFIX = "R"
_REQ_PREFIX = "REQ"
_DEFECT_PREFIX = "SUIT"

# Transient attribute name. Not a mapped column on any model — set on the
# instance just before flush by the repo layer (see ``set_workspace_id`` below).
_WS_ATTR = "_workspace_id_for_pubid"


# --- transient-attr helpers ---------------------------------------------------


def set_workspace_id(target: object, workspace_id: str) -> None:
    """Attach the workspace context used by the ``before_insert`` listener.

    Uses ``object.__setattr__`` so mypy never sees a fictitious attribute on
    the SQLAlchemy model classes (the attr is genuinely transient — never
    declared as ``Mapped[...]``).
    """
    object.__setattr__(target, _WS_ATTR, workspace_id)


def _get_workspace_id(target: object) -> str | None:
    return getattr(target, _WS_ATTR, None)


# --- async wrapper ------------------------------------------------------------


async def generate_public_id(db: AsyncSession, prefix: str, workspace_id: str) -> str:
    """Call ``generate_public_id(prefix, workspace_id)`` on Postgres and return it.

    Service-layer wrapper per docs/DATA_MODEL.md §8. Used when code needs a
    public ID outside of an ``INSERT`` (e.g. preview UI). For inserts the
    per-model ``before_insert`` listeners below handle it transparently.
    """
    row = await db.execute(
        text("SELECT generate_public_id(:p, :w) AS pid"),
        {"p": prefix, "w": workspace_id},
    )
    pid: str = row.scalar_one()
    return pid


# --- listener internals -------------------------------------------------------


def _assign_public_id(target: object, conn: Connection, prefix: str) -> None:
    """Shared ``before_insert`` body for all four models.

    - Returns early if ``target.public_id`` is already set (idempotent — lets
      seeders/migrations pin specific IDs).
    - Raises ``RuntimeError`` if the repo layer forgot to attach
      ``_workspace_id_for_pubid``; the missing context is a programmer error
      and should fail loudly rather than silently generating against a
      placeholder.
    """
    if getattr(target, "public_id", None):
        return
    ws_id = _get_workspace_id(target)
    if not ws_id:
        raise RuntimeError(
            f"{type(target).__name__}.public_id requires "
            f"{_WS_ATTR} transient attribute — set it via "
            "suitest_db.public_id.set_workspace_id(target, workspace_id) "
            "before flush."
        )
    new_pid = conn.execute(
        text("SELECT generate_public_id(:p, :w)"),
        {"p": prefix, "w": ws_id},
    ).scalar_one()
    object.__setattr__(target, "public_id", new_pid)


# --- listeners ----------------------------------------------------------------
#
# Each listener is a thin shim that delegates to ``_assign_public_id`` with the
# right prefix. Typed with ``Mapper[Model]`` + ``Connection`` per SQLAlchemy 2
# event signatures.


@event.listens_for(TestCase, "before_insert")
def _tc_public_id(mapper: Mapper[TestCase], connection: Connection, target: TestCase) -> None:
    _assign_public_id(target, connection, _TC_PREFIX)


@event.listens_for(Run, "before_insert")
def _run_public_id(mapper: Mapper[Run], connection: Connection, target: Run) -> None:
    _assign_public_id(target, connection, _RUN_PREFIX)


@event.listens_for(Requirement, "before_insert")
def _req_public_id(
    mapper: Mapper[Requirement], connection: Connection, target: Requirement
) -> None:
    _assign_public_id(target, connection, _REQ_PREFIX)


@event.listens_for(Defect, "before_insert")
def _defect_public_id(mapper: Mapper[Defect], connection: Connection, target: Defect) -> None:
    _assign_public_id(target, connection, _DEFECT_PREFIX)
