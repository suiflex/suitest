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

import aioboto3

from suitest_api.settings import get_settings

SIGNED_URL_TTL_SECONDS = 3600
UPLOAD_ROOT = "uploads"


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
    """Store bytes under the workspace prefix; return ``(s3_url, key, size)``."""
    settings = get_settings()
    key = f"{workspace_prefix(workspace_id)}{uuid.uuid4().hex}/{_safe_name(filename)}"
    async with aioboto3.Session().client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    ) as client:
        await client.put_object(
            Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type
        )
    return f"s3://{settings.s3_bucket}/{key}", key, len(data)


async def presign_get(key: str) -> str:
    """Time-limited presigned GET URL for an object the caller already owns."""
    settings = get_settings()
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
    async with aioboto3.Session().client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    ) as client:
        await client.delete_object(Bucket=settings.s3_bucket, Key=key)
