"""api_keys: store the full key AES-GCM encrypted (retrievable copy).

Adds ``key_encrypted`` so the management UI can copy the REAL key from each row
(product decision: convenience over strict show-once, acceptable for self-hosted
instances). The SHA-256 ``key_hash`` is still the auth path; this column is only
read by admins on the list surface. Existing rows have NULL (created before this
migration → not retrievable, only their prefix shows).

Revision ID: 0043_api_key_encrypted
Revises: 0042_api_keys
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0043_api_key_encrypted"
down_revision: str | None = "0042_api_keys"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("key_encrypted", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "key_encrypted")
