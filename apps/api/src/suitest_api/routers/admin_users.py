"""M1e password management endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.user import User
from suitest_db.repositories.password_reset_requests import PasswordResetRequestRepository

from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import current_active_user
from suitest_api.services.password_service import (
    InvalidCurrentPasswordError,
    PasswordService,
    UserNotFoundError,
)

router = APIRouter(prefix="/api/v1", tags=["users"])


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class ResetPasswordResponse(BaseModel):
    temporary_password: str = Field(serialization_alias="temporaryPassword")


class PasswordResetRequestOut(BaseModel):
    id: str
    email: str
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime
    reset_link: str | None = Field(serialization_alias="resetLink")


class PasswordResetRequestsEnvelope(BaseModel):
    items: list[PasswordResetRequestOut]


@router.patch("/users/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_own_password(
    body: ChangePasswordRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    svc = PasswordService(session)
    try:
        await svc.change_own_password(
            user=user,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except InvalidCurrentPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="current password is invalid",
        ) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/admin/users/{user_id}/reset-password",
    response_model=ResetPasswordResponse,
    response_model_by_alias=True,
)
async def reset_user_password(
    user_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> ResetPasswordResponse:
    svc = PasswordService(session)
    try:
        temporary = await svc.reset_user_password_as_superadmin(actor=user, target_user_id=user_id)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="super-admin required"
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found") from exc
    await session.commit()
    return ResetPasswordResponse(temporary_password=temporary)


@router.get(
    "/admin/password-reset-requests",
    response_model=PasswordResetRequestsEnvelope,
    response_model_by_alias=True,
)
async def list_password_reset_requests(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> PasswordResetRequestsEnvelope:
    if not user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="super-admin required")
    rows = await PasswordResetRequestRepository(session).list_recent()
    return PasswordResetRequestsEnvelope(
        items=[
            PasswordResetRequestOut(
                id=row.id,
                email=row.email,
                expires_at=row.expires_at,
                used_at=row.used_at,
                created_at=row.created_at,
                reset_link=row.reset_link_encrypted,
            )
            for row in rows
        ]
    )
