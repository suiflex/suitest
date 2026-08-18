"""LLMConfig model — workspace LLM provider with encrypted key (docs/DATA_MODEL.md §4.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from suitest_core.crypto import EncryptedBytes

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id
from suitest_db.types import PortableJSON

#: ``auth_method`` values. A pasted key, or Sign in with ChatGPT.
AUTH_METHOD_API_KEY = "api_key"
AUTH_METHOD_OAUTH = "oauth"


class StoredOAuthTokens(BaseModel):
    """Shape of the ``oauth_tokens_encrypted`` blob.

    One encrypted JSON blob rather than a column per token: a refresh rewrites
    the whole set anyway, and nothing queries by token or expiry.

    ponytail: split into columns only once something needs to filter on expiry.
    """

    access_token: str
    refresh_token: str | None = None
    id_token: str | None = None
    expires_at: datetime | None = None
    #: ``chatgpt-account-id`` header value for ChatGPT-backend calls.
    account_id: str | None = None
    #: Signed-in account, shown back to the admin as a hint.
    email: str | None = None


class LLMConfig(Base, TimestampMixin):
    __tablename__ = "llm_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)

    # AES-GCM (DATA_MODEL §12). Nullable so ZERO tier can store a row with no key.
    api_key_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)

    # How the provider authenticates: a pasted key, or Sign in with ChatGPT.
    auth_method: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AUTH_METHOD_API_KEY, server_default=AUTH_METHOD_API_KEY
    )
    # AES-GCM JSON blob of :class:`StoredOAuthTokens`; set only for OAuth configs.
    oauth_tokens_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)

    config_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_llm_configs_workspace_active", "workspace_id", "is_active"),)

    @property
    def base_url(self) -> str | None:
        """Normalized optional provider base URL from the stored configuration."""
        value = self.config_json.get("base_url")
        return value if isinstance(value, str) else None

    @property
    def oauth_tokens(self) -> StoredOAuthTokens | None:
        """Decoded OAuth token set, or ``None`` for an API-key config."""
        blob = self.oauth_tokens_encrypted
        if not blob:
            return None
        return StoredOAuthTokens.model_validate_json(blob)
