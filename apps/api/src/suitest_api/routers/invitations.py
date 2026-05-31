"""M1e invitation routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.user import User
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import auth_backend, current_active_user, get_jwt_strategy
from suitest_api.services.invitation_service import (
    InvitationConflictError,
    InvitationForbiddenError,
    InvitationNotFoundError,
    InvitationService,
)
from suitest_api.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["invitations"])


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role: Role


class InvitationOut(BaseModel):
    id: str
    email: str
    role: Role
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    link: str | None = None


class InvitationListEnvelope(BaseModel):
    items: list[InvitationOut]


class InvitationValidateResponse(BaseModel):
    email: str
    role: Role
    workspace_name: str
    expires_at: datetime


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8)


class AcceptInviteResponse(BaseModel):
    ok: bool = True


def _service(session: AsyncSession) -> InvitationService:
    settings = get_settings()
    return InvitationService(
        session,
        web_url=settings.web_url,
        ttl_hours=settings.invite_ttl_hours,
    )


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    workspace_id: str,
    body: InvitationCreateRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> InvitationOut:
    try:
        outcome = await _service(session).create_invitation(
            workspace_id=workspace_id,
            email=str(body.email),
            role=body.role,
            actor=user,
        )
    except InvitationForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden") from exc
    except InvitationConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="already a member"
        ) from exc
    await session.commit()
    inv = outcome.invitation
    return InvitationOut(
        id=inv.id,
        email=inv.email,
        role=inv.role,
        expires_at=inv.expires_at,
        accepted_at=inv.accepted_at,
        revoked_at=inv.revoked_at,
        link=outcome.link,
    )


@router.get(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationListEnvelope,
)
async def list_invitations(
    workspace_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> InvitationListEnvelope:
    try:
        rows = await _service(session).list_invitations(workspace_id=workspace_id, actor=user)
    except InvitationForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden") from exc
    return InvitationListEnvelope(
        items=[
            InvitationOut(
                id=row.id,
                email=row.email,
                role=row.role,
                expires_at=row.expires_at,
                accepted_at=row.accepted_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ]
    )


@router.get(
    "/invitations/validate",
    response_model=InvitationValidateResponse,
)
async def validate_invitation(
    token: str = Query(min_length=1),
    session: AsyncSession = Depends(get_async_session),
) -> InvitationValidateResponse:
    try:
        inv = await _service(session).validate_token(token)
    except InvitationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invite not found"
        ) from exc
    return InvitationValidateResponse(
        email=inv.email,
        role=inv.role,
        workspace_name=inv.workspace.name,
        expires_at=inv.expires_at,
    )


@router.post("/invitations/{invitation_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    try:
        await _service(session).revoke(invitation_id=invitation_id, actor=user)
    except InvitationForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden") from exc
    except InvitationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invite not found"
        ) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invitations/{invitation_id}/resend", response_model=InvitationOut)
async def resend_invitation(
    invitation_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> InvitationOut:
    try:
        outcome = await _service(session).resend(invitation_id=invitation_id, actor=user)
    except InvitationForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden") from exc
    except InvitationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invite not found"
        ) from exc
    await session.commit()
    inv = outcome.invitation
    return InvitationOut(
        id=inv.id,
        email=inv.email,
        role=inv.role,
        expires_at=inv.expires_at,
        accepted_at=inv.accepted_at,
        revoked_at=inv.revoked_at,
        link=outcome.link,
    )


@router.post(
    "/auth/accept-invite",
    response_model=AcceptInviteResponse,
)
async def accept_invitation(
    body: AcceptInviteRequest,
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    try:
        user = await _service(session).accept(
            token=body.token,
            name=body.name,
            password=body.password,
        )
    except InvitationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invite not found"
        ) from exc
    await session.commit()
    # FastAPI-Users' CookieTransport login yields a 204 carrying only the
    # Set-Cookie header. The accept-invite contract returns a JSON body
    # (``AcceptInviteResponse``) AND sets the session cookie, so build a 200
    # JSON response and graft the auth cookie onto it.
    login_response = await auth_backend.login(get_jwt_strategy(), user)
    response = JSONResponse(content={"ok": True}, status_code=status.HTTP_200_OK)
    for key, value in login_response.raw_headers:
        if key.lower() == b"set-cookie":
            response.raw_headers.append((key, value))
    return response
