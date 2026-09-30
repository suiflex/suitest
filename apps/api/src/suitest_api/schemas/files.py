"""Request/response schemas for the workspace file-store endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Camel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class FileUploadResult(_Camel):
    """Result of storing an uploaded object server-side."""

    url: str  # durable s3://bucket/key — referenced from ingest payloads
    key: str  # workspace-scoped object key (for later sign/delete)
    size_bytes: int = Field(alias="sizeBytes")
    mime_type: str = Field(alias="mimeType")


class FileSignedUrl(_Camel):
    """Time-limited presigned GET URL for an owned object."""

    url: str
    expires_in_seconds: int = Field(alias="expiresInSeconds")


class FixtureUploadItem(_Camel):
    file_name: str = Field(alias="fileName")
    base64: str
    content_type: str | None = Field(default=None, alias="contentType")


class FixtureUploadRequest(_Camel):
    files: list[FixtureUploadItem]


class FixtureUploadResponse(_Camel):
    fixture_paths: list[str] = Field(alias="fixturePaths")
    file_names: list[str] = Field(alias="fileNames")
