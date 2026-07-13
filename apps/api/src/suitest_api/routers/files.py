"""Workspace file store — upload/sign/delete artifact blobs via the API.

The lifecycle publisher and MCP clients push artifact bytes here instead of
talking to S3 directly, so object-store credentials stay server-side (out of
``.mcp.json`` / CI env). Every object is namespaced under the caller's workspace
and the read/delete paths reject keys outside that prefix — a key can only touch
its own uploads. Authenticated by API key OR session (same as the ingest path).
"""

from __future__ import annotations

import mimetypes

import anyio
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import write_audit

from suitest_api.auth.db import get_async_session
from suitest_api.deps.api_key import tenant_via_api_key_or_session
from suitest_api.deps.scope import TenantContext
from suitest_api.schemas.files import FileSignedUrl, FileUploadResult
from suitest_api.services import file_storage

router = APIRouter(prefix="/api/v1", tags=["files"])

# 512 MiB ceiling — comfortably covers run videos + traces without letting a
# client exhaust memory/storage on a single request.
_MAX_UPLOAD_BYTES = 512 * 1024 * 1024


@router.post("/files", response_model=FileUploadResult, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(description="Artifact blob (video, screenshot, trace, …)."),
    ctx: TenantContext = Depends(tenant_via_api_key_or_session),
    session: AsyncSession = Depends(get_async_session),
) -> FileUploadResult:
    """Store an uploaded blob in the workspace's object store; return its s3:// URL."""
    size = file.size
    if size is None:
        # Defensive fallback for ASGI clients that omit multipart size metadata.
        def _measure() -> int:
            file.file.seek(0, 2)
            return file.file.tell()

        size = await anyio.to_thread.run_sync(_measure)
        await file.seek(0)
    if size == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")
    if size > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds {_MAX_UPLOAD_BYTES} bytes",
        )
    content_type = file.content_type or "application/octet-stream"
    await file.seek(0)
    url, key, stored_size = await file_storage.upload_fileobj(
        workspace_id=ctx.workspace_id,
        filename=file.filename or "file",
        source=file.file,
        size=size,
        content_type=content_type,
    )
    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="file.upload",
        resource_type="file",
        # ``resource_id`` is varchar(64); the full S3 key can exceed that, so
        # audit by the object's short uuid segment and keep the key in metadata.
        resource_id=file_storage.object_id(key),
        metadata={"key": key, "size_bytes": stored_size, "mime_type": content_type},
    )
    await session.commit()
    return FileUploadResult(url=url, key=key, size_bytes=stored_size, mime_type=content_type)


@router.get("/files/signed-url", response_model=FileSignedUrl)
async def sign_file(
    key: str = Query(description="Workspace-scoped object key returned by the upload."),
    ctx: TenantContext = Depends(tenant_via_api_key_or_session),
) -> FileSignedUrl:
    """Return a presigned GET URL for an object the caller owns (404 otherwise)."""
    if not file_storage.key_in_workspace(key, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    url = await file_storage.presign_get(key)
    return FileSignedUrl(url=url, expires_in_seconds=file_storage.SIGNED_URL_TTL_SECONDS)


@router.get("/files/raw")
async def get_file_raw(
    key: str = Query(description="Workspace-scoped object key returned by the upload."),
    ctx: TenantContext = Depends(tenant_via_api_key_or_session),
) -> FileResponse:
    """Stream one owned object from disk (local mode — the signed-url target)."""
    if not file_storage.key_in_workspace(key, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    path = file_storage.local_path(key)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=mime)


@router.delete("/files", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    key: str = Query(description="Workspace-scoped object key to delete."),
    ctx: TenantContext = Depends(tenant_via_api_key_or_session),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Delete an object the caller owns (no-op-safe; 404 for out-of-scope keys)."""
    if not file_storage.key_in_workspace(key, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    await file_storage.delete(key)
    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="file.delete",
        resource_type="file",
        resource_id=file_storage.object_id(key),
        metadata={"key": key},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
