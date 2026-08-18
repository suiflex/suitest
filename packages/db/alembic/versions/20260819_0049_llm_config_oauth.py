"""Store OAuth credentials on llm_configs (Sign in with ChatGPT).

Revision ID: 0049_llm_config_oauth
Revises: 0048_fe_desktop_target_kind
Create Date: 2026-08-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0049_llm_config_oauth"
down_revision: str | None = "0048_fe_desktop_target_kind"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Existing rows all authenticate by pasted key, hence the server default.
    op.add_column(
        "llm_configs",
        sa.Column(
            "auth_method",
            sa.String(length=16),
            nullable=False,
            server_default="api_key",
        ),
    )
    # AES-GCM blob holding the whole token set as JSON, so a refresh rewrites one
    # column and no plaintext token ever reaches the database.
    op.add_column(
        "llm_configs",
        sa.Column("oauth_tokens_encrypted", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_configs", "oauth_tokens_encrypted")
    op.drop_column("llm_configs", "auth_method")
