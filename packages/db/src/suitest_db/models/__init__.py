"""Model registry side-effect imports.

Importing every model module here ensures SQLAlchemy's declarative registry (and
therefore Alembic autogenerate) sees all tables. This is NOT a barrel — symbols
are NOT re-exported (CLAUDE.md §2.2). Import models from their own module, e.g.
``from suitest_db.models.tenancy import Membership``.
"""

import suitest_db.models.tenancy as _tenancy  # noqa: F401
import suitest_db.models.user as _user  # noqa: F401
import suitest_db.models.workspace as _workspace  # noqa: F401
