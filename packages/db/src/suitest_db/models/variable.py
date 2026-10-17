"""Workspace & Suite variables and credentials models with AES-GCM encryption."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from suitest_core.crypto import EncryptedBytes

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class WorkspaceVariable(Base, TimestampMixin):
    """Workspace-level variable or credential."""

    __tablename__ = "workspace_variables"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    value_plain: Mapped[str | None] = mapped_column(Text)
    secret_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)

    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_workspace_variables_key"),
        Index("ix_workspace_variables_workspace", "workspace_id"),
    )

    def __init__(
        self,
        *,
        workspace_id: str | None = None,
        key: str | None = None,
        value: str | None = None,
        is_secret: bool = False,
        description: str | None = None,
        **kwargs: Any,
    ) -> None:
        if workspace_id is not None:
            kwargs["workspace_id"] = workspace_id
        if key is not None:
            kwargs["key"] = key
        kwargs["is_secret"] = is_secret
        if description is not None:
            kwargs["description"] = description
        super().__init__(**kwargs)
        if value is not None:
            self.value = value

    @property
    def value(self) -> str | None:
        if self.is_secret:
            return self.secret_encrypted
        return self.value_plain

    @value.setter
    def value(self, val: str | None) -> None:
        if self.is_secret:
            self.secret_encrypted = val
            self.value_plain = None
        else:
            self.value_plain = val
            self.secret_encrypted = None


class SuiteVariable(Base, TimestampMixin):
    """Suite-level variable or credential override."""

    __tablename__ = "suite_variables"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    suite_id: Mapped[str] = mapped_column(
        ForeignKey("suites.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    value_plain: Mapped[str | None] = mapped_column(Text)
    secret_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)

    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("suite_id", "key", name="uq_suite_variables_key"),
        Index("ix_suite_variables_suite", "suite_id"),
    )

    def __init__(
        self,
        *,
        suite_id: str | None = None,
        key: str | None = None,
        value: str | None = None,
        is_secret: bool = False,
        description: str | None = None,
        **kwargs: Any,
    ) -> None:
        if suite_id is not None:
            kwargs["suite_id"] = suite_id
        if key is not None:
            kwargs["key"] = key
        kwargs["is_secret"] = is_secret
        if description is not None:
            kwargs["description"] = description
        super().__init__(**kwargs)
        if value is not None:
            self.value = value

    @property
    def value(self) -> str | None:
        if self.is_secret:
            return self.secret_encrypted
        return self.value_plain

    @value.setter
    def value(self, val: str | None) -> None:
        if self.is_secret:
            self.secret_encrypted = val
            self.value_plain = None
        else:
            self.value_plain = val
            self.secret_encrypted = None
