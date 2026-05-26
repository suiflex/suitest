"""Pydantic schemas exposed by FastAPI-Users routes."""

import uuid

from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Outbound user representation."""


class UserCreate(schemas.BaseUserCreate):
    """Inbound payload for POST /auth/register."""


class UserUpdate(schemas.BaseUserUpdate):
    """Inbound payload for PATCH /users/me."""
