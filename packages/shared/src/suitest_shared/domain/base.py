"""Base Pydantic v2 domain model (docs/DATA_MODEL.md §2).

Domain models are **DB-agnostic** — they do not import SQLAlchemy. The service /
repository layer maps ORM rows ↔ domain models. ``from_attributes=True`` lets a
domain model be built directly from an ORM row.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Common config for every Suitest domain model."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        populate_by_name=True,
        use_enum_values=False,
    )
