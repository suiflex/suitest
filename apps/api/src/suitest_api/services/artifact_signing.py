"""Presigned artifact URL helper (docs/API.md §3.5).

Two storage schemes:

* ``s3://`` / ``https://`` (MinIO/R2 object store) — produce a time-limited
  presigned GET URL. The actual presign call is isolated behind the module-level
  :func:`_presign` so tests monkeypatch it without a ``minio`` dependency; M3 swaps
  the stub for ``minio.Minio.presigned_get_object``.
* ``file://`` (single-host volume mode) — there is no object store to presign
  against, so we return a placeholder URL pointing at the (not-yet-implemented in
  M1a) ``/artifacts/raw/{id}`` route, discriminated by ``kind="file"``.

The ``kind`` discriminator lets the frontend decide whether to fetch the URL
directly (``s3``) or route through the app (``file``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

DEFAULT_SIGNED_URL_TTL = 900  # seconds


@dataclass(frozen=True)
class SignedArtifact:
    """Result of signing an artifact object for download."""

    url: str
    scheme: str  # "s3" (presigned object store) | "file" (single-host placeholder)
    expires_at: datetime


def _presign(object_url: str, *, expires_in: int) -> str:
    """Stub presigner. Replaced by ``minio.Minio.presigned_get_object`` in M3.

    Tests monkeypatch this module-level function. The M1a stub appends a query
    string so the shape is realistic.
    """
    return f"{object_url}?X-Amz-Expires={expires_in}&X-Amz-Signature=stub"


def build_signed_url(
    *,
    artifact_id: str,
    object_url: str,
    expires_in: int = DEFAULT_SIGNED_URL_TTL,
) -> SignedArtifact:
    """Sign an artifact object for download.

    ``scheme`` is ``"s3"`` for presignable object stores, ``"file"`` for single-host
    volume artifacts (a placeholder URL pointing at the future ``/artifacts/raw/{id}``).
    """
    expires_at = datetime.now(tz=UTC) + timedelta(seconds=expires_in)
    if object_url.startswith("file://"):
        return SignedArtifact(
            url=f"/artifacts/raw/{artifact_id}", scheme="file", expires_at=expires_at
        )
    return SignedArtifact(
        url=_presign(object_url, expires_in=expires_in), scheme="s3", expires_at=expires_at
    )
