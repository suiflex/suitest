"""First-install bootstrap for self-host operators."""

from __future__ import annotations

import re
import uuid

from fastapi_users.password import PasswordHelper
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import AutonomyLevel, Role, Tier

from suitest_api.settings import Settings


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "default-workspace"


async def bootstrap_first_install_superadmin(session: AsyncSession, settings: Settings) -> bool:
    """Create first super-admin + default workspace when DB has no users.

    Returns True only when rows were created. Missing env or an existing user
    makes this a no-op.
    """
    existing_users = await session.scalar(select(func.count()).select_from(User))
    if int(existing_users or 0) > 0:
        return False
    email = settings.superadmin_email.strip().lower()
    password = settings.superadmin_password
    if not email or not password:
        return False

    workspace_name = settings.superadmin_workspace_name.strip() or "Default Workspace"
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=PasswordHelper().hash(password),
        is_active=True,
        is_superuser=True,
        is_verified=True,
        name=email.split("@", 1)[0],
    )
    workspace = Workspace(slug=_slugify(workspace_name), name=workspace_name)
    session.add_all([user, workspace])
    await session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.OWNER))
    session.add(
        WorkspaceCapability(
            workspace_id=workspace.id,
            tier=Tier.ZERO,
            autonomy_level=AutonomyLevel.MANUAL,
            features_json={},
        )
    )
    await session.flush()
    return True
