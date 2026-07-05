"""Portable column types across dialects (PostgreSQL + SQLite)."""

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on PostgreSQL, text-based JSON on SQLite/other dialects.
PortableJSON = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")
