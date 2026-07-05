"""Artifact storage backends: local disk (local mode) & S3/MinIO (server mode)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import aioboto3
from botocore.config import Config

if TYPE_CHECKING:
    from suitest_runner.settings import RunnerSettings


class ArtifactStorage(Protocol):
    """Minimal write interface the artifact pipeline needs."""

    async def put(self, *, key: str, body: bytes, content_type: str) -> str:
        """Store ``body`` at ``key``; return the URL for the artifacts.url column."""
        ...


class LocalStorage:
    """Writes artifacts as plain files under a root folder; URLs are ``local://<key>``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    async def put(self, *, key: str, body: bytes, content_type: str) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        # ponytail: sync write — one artifact per step, not a hot path;
        # move to anyio.to_thread if large videos prove blocking.
        path.write_bytes(body)
        return f"local://{key}"


class S3Storage:
    """Uploads via aioboto3 to any S3-compatible endpoint; URLs are ``s3://bucket/key``."""

    def __init__(self, settings: RunnerSettings) -> None:
        self._settings = settings

    async def put(self, *, key: str, body: bytes, content_type: str) -> str:
        settings = self._settings
        # Disable client-side checksum signing + chunked encoding. botocore 1.36+
        # ships a SHA-256 checksum + ``aws-chunked`` transfer encoding by default
        # for S3 put_object, which moto's mock S3 cannot decode in async mode
        # (it tries to call ``.readline()`` on an unread coroutine body). MinIO
        # and real S3 both happily accept the simpler legacy signing path.
        s3_config = Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            signature_version="s3v4",
        )
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=s3_config,
        ) as client:
            await client.put_object(
                Bucket=settings.s3_bucket, Key=key, Body=body, ContentType=content_type
            )
        return f"s3://{settings.s3_bucket}/{key}"


def make_storage(settings: RunnerSettings) -> ArtifactStorage:
    """Select the artifact backend from ``settings.artifacts_backend``."""
    if settings.artifacts_backend == "local":
        return LocalStorage(root=Path(settings.artifacts_dir))
    return S3Storage(settings)
