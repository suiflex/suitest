"""Server-side object storage for lifecycle / MCP uploads.

Lets an API-key client (the lifecycle publisher, an IDE's MCP server, CI) push
artifact bytes — videos, per-step screenshots — into the platform's object store
WITHOUT holding any ``SUITEST_S3_*`` credentials itself. The server owns the S3
config; the client only holds its API key. This keeps object-store secrets out
of every ``.mcp.json`` / CI environment.

Every object is namespaced under the caller's workspace
(``uploads/<workspace_id>/…``) so a key can only ever sign or delete its OWN
uploads — the read/delete paths reject any key outside that prefix.
"""

from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote

import aioboto3
import anyio

from suitest_api.settings import get_settings

SIGNED_URL_TTL_SECONDS = 3600
UPLOAD_ROOT = "uploads"


def local_path(key: str) -> Path:
    """Absolute path a workspace-scoped key resolves to under ``artifacts_dir``.

    Uploads share the runner's artifacts root so the existing ``local://``
    read paths (``GET /runs/:id/artifacts/:id/raw``) serve them unchanged.
    """
    return Path(get_settings().artifacts_dir).resolve() / key


def workspace_prefix(workspace_id: str) -> str:
    """S3 key prefix that scopes every object to one workspace."""
    return f"{UPLOAD_ROOT}/{workspace_id}/"


def key_in_workspace(key: str, workspace_id: str) -> bool:
    """True iff ``key`` is a well-formed object under the workspace's prefix."""
    return key.startswith(workspace_prefix(workspace_id)) and ".." not in key


def object_id(key: str) -> str:
    """Short (≤64-char) id for a key — the uuid segment, for audit ``resource_id``."""
    parts = key.split("/")
    return parts[2] if len(parts) >= 3 else key[:64]


def _safe_name(name: str) -> str:
    """Reduce a client filename to a safe basename (no path, no separators)."""
    base = name.replace("\\", "/").split("/")[-1]
    cleaned = "".join(c for c in base if c.isalnum() or c in "._-")
    return cleaned or "file"


async def upload(
    *, workspace_id: str, filename: str, data: bytes, content_type: str
) -> tuple[str, str, int]:
    """Store bytes under the workspace prefix; return ``(url, key, size)``.

    ``server`` mode puts the object in S3 and returns an ``s3://`` URL. ``local``
    mode (npx bundle — no MinIO) writes under ``artifacts_dir`` and returns a
    ``local://`` URL, which the runs artifact routes already know how to serve.
    """
    return await upload_fileobj(
        workspace_id=workspace_id,
        filename=filename,
        source=BytesIO(data),
        size=len(data),
        content_type=content_type,
    )


async def upload_fileobj(
    *,
    workspace_id: str,
    filename: str,
    source: BinaryIO,
    size: int,
    content_type: str,
) -> tuple[str, str, int]:
    """Store a seekable stream without materialising it as one giant ``bytes``.

    Starlette spools large multipart parts to disk. Keeping that stream intact
    bounds API memory for both local SQLite/disk installs and S3 deployments.
    """
    settings = get_settings()
    key = f"{workspace_prefix(workspace_id)}{uuid.uuid4().hex}/{_safe_name(filename)}"
    if settings.mode == "local":
        path = local_path(key)
        source.seek(0)

        def _copy() -> None:
            import shutil

            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)

        await anyio.to_thread.run_sync(_copy)
        return f"local://{key}", key, size
    source.seek(0)
    async with aioboto3.Session().client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    ) as client:
        await client.put_object(
            Bucket=settings.s3_bucket, Key=key, Body=source, ContentType=content_type
        )
    return f"s3://{settings.s3_bucket}/{key}", key, size


async def presign_get(key: str) -> str:
    """GET URL for an object the caller already owns.

    ``server`` mode presigns against S3; ``local`` mode has no presigning, so it
    returns the raw streaming route on this same API (auth-gated there).
    """
    settings = get_settings()
    if settings.mode == "local":
        return f"/api/v1/files/raw?key={quote(key, safe='')}"
    async with aioboto3.Session().client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    ) as client:
        url: str = await client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=SIGNED_URL_TTL_SECONDS,
        )
    return url


async def delete(key: str) -> None:
    """Delete one owned object."""
    settings = get_settings()
    if settings.mode == "local":
        local_path(key).unlink(missing_ok=True)
        return
    async with aioboto3.Session().client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    ) as client:
        await client.delete_object(Bucket=settings.s3_bucket, Key=key)
