"""Generic async repository — centralises CRUD + keyset pagination.

Every concrete repo binds ``ModelT`` to one SQLAlchemy model and supplies
``model`` as a class attribute. Services never build queries inline; they go
through these repos so SQL stays in one place and stays typed.

``list_paginated`` implements ``(created_at, id)`` keyset (a.k.a. seek) pagination
which is stable under inserts and O(1) per page, unlike OFFSET. It requires the
model to expose both ``created_at`` and ``id`` columns (i.e. a ``TimestampMixin``
model); calling it on a timestamp-less association table raises ``AttributeError``.

The model columns (``id``, ``created_at``) are accessed via ``getattr`` and typed
as ``InstrumentedAttribute`` because ``ModelT`` is only bound to ``Base`` (which
declares no columns of its own); concrete column types are resolved at runtime.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, select, tuple_
from sqlalchemy.orm import InstrumentedAttribute
from suitest_db.base import Base

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

# A repo filter maps a model column name to a scalar value compared with ``==``.
Filters = dict[str, object]


class AsyncRepository[ModelT: Base, CreateDTO: BaseModel, UpdateDTO: BaseModel]:
    """Typed async CRUD base. Subclasses set ``model`` and add domain helpers.

    Uses PEP 695 type parameters (Python 3.12+): ``ModelT`` is the SQLAlchemy
    model, ``CreateDTO`` / ``UpdateDTO`` the Pydantic write payloads.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- column accessors --------------------------------------------------

    def _col(self, name: str) -> InstrumentedAttribute[Any]:
        # Generic dynamic column access: the column's Python type is unknown to the
        # type checker (``ModelT`` is only bound to ``Base``), and SQLAlchemy's own
        # operator overloads (``==``, ``.desc()``, ``tuple_``) require an
        # ``InstrumentedAttribute[Any]`` to resolve to ``ColumnElement[bool]`` rather
        # than ``object.__eq__``. This is the one sanctioned ``Any`` in the data layer.
        attr = getattr(self.model, name, None)
        if not isinstance(attr, InstrumentedAttribute):
            raise AttributeError(f"{self.model.__name__} has no column {name!r}")
        return attr

    @property
    def _id_col(self) -> InstrumentedAttribute[Any]:
        return self._col("id")

    # -- read --------------------------------------------------------------

    async def get_by_id(self, id: str) -> ModelT | None:
        result: ModelT | None = await self.session.scalar(
            select(self.model).where(self._id_col == id)
        )
        return result

    async def get_by_public_id(self, public_id: str) -> ModelT | None:
        column = self._col("public_id")
        result: ModelT | None = await self.session.scalar(
            select(self.model).where(column == public_id)
        )
        return result

    async def list_paginated(
        self,
        *,
        cursor: tuple[datetime, str] | None,
        limit: int = 20,
        filters: Filters | None = None,
    ) -> tuple[Sequence[ModelT], tuple[datetime, str] | None]:
        """Return one keyset page plus the cursor for the next page.

        Orders by ``(created_at, id)`` descending. Fetches ``limit + 1`` rows to
        detect whether a further page exists: if it does, the extra row is dropped
        and its predecessor's ``(created_at, id)`` becomes ``next_cursor``;
        otherwise ``next_cursor`` is ``None``.
        """
        created_at = self._col("created_at")
        id_col = self._id_col
        stmt = select(self.model)
        for clause in self._filter_clauses(filters):
            stmt = stmt.where(clause)
        if cursor is not None:
            stmt = stmt.where(tuple_(created_at, id_col) < cursor)
        stmt = stmt.order_by(created_at.desc(), id_col.desc()).limit(limit + 1)

        rows = list((await self.session.scalars(stmt)).all())
        return self._paginate(rows, limit)

    async def count(self, filters: Filters | None = None) -> int:
        stmt = select(func.count()).select_from(self.model)
        for clause in self._filter_clauses(filters):
            stmt = stmt.where(clause)
        result = await self.session.scalar(stmt)
        return result or 0

    # -- write -------------------------------------------------------------

    async def create(self, dto: CreateDTO) -> ModelT:
        row = self.model(**dto.model_dump(exclude_unset=True))
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, id: str, dto: UpdateDTO) -> ModelT | None:
        row = await self.get_by_id(id)
        if row is None:
            return None
        for field, value in dto.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(row, field, value)
        await self.session.flush()
        return row

    async def soft_delete(self, id: str) -> bool:
        if not hasattr(self.model, "deleted_at"):
            raise AttributeError(f"{self.model.__name__} has no deleted_at column")
        row = await self.get_by_id(id)
        if row is None:
            return False
        row.deleted_at = datetime.now(tz=UTC)  # type: ignore[attr-defined]
        await self.session.flush()
        return True

    # -- internal ----------------------------------------------------------

    def _paginate(
        self, rows: list[ModelT], limit: int
    ) -> tuple[Sequence[ModelT], tuple[datetime, str] | None]:
        if len(rows) > limit:
            page = rows[:limit]
            last = page[-1]
            next_cursor: tuple[datetime, str] | None = (
                cast("datetime", getattr(last, "created_at")),  # noqa: B009
                cast("str", getattr(last, "id")),  # noqa: B009
            )
            return page, next_cursor
        return rows, None

    def _filter_clauses(self, filters: Filters | None) -> list[ColumnElement[bool]]:
        if not filters:
            return []
        clauses: list[ColumnElement[bool]] = []
        for key, value in filters.items():
            clauses.append(self._col(key) == value)
        return clauses
