"""Document exports scoped by project -> workspace. UAT ("Berita Acara") PDF."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import write_audit

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.services.uat_document import Locale
from suitest_api.services.uat_document_service import UatDocumentService, UatExportError

router = APIRouter(prefix="/api/v1", tags=["exports"])


class UatExportBody(BaseModel):
    case_ids: list[str] = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=200)
    locale: Locale = "id"


@router.post("/projects/{project_id}/exports/uat", response_class=Response)
async def export_uat_document(
    project_id: str,
    body: UatExportBody,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Build a Suitest-branded UAT sign-off PDF from the selected test cases.

    Each case contributes its latest-run status + screenshot evidence. ZERO-tier,
    deterministic. 404 when any case is outside this project/workspace.
    """
    service = UatDocumentService(session)
    try:
        pdf = await service.build_pdf(
            project_id=project_id,
            workspace_id=ctx.workspace_id,
            case_ids=body.case_ids,
            title=body.title,
            locale=body.locale,
        )
    except UatExportError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="uat_export",
        resource_type="project",
        resource_id=project_id,
        metadata={"case_count": len(body.case_ids), "locale": body.locale},
    )
    filename = f"uat-{project_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
