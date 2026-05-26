"""SQLAlchemy models. Import here to keep Alembic autogenerate happy."""

from suitest_db.models.user import OAuthAccount, User
from suitest_db.models.workspace import Workspace

__all__ = ["OAuthAccount", "User", "Workspace"]
