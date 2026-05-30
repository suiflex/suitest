"""Model registry side-effect imports.

Importing every model module here ensures SQLAlchemy's declarative registry (and
therefore Alembic autogenerate) sees all tables. This is NOT a barrel — symbols
are NOT re-exported (CLAUDE.md §2.2). Import models from their own module, e.g.
``from suitest_db.models.tenancy import Membership``.
"""

import suitest_db.models.agent as _agent  # noqa: F401
import suitest_db.models.audit as _audit  # noqa: F401
import suitest_db.models.case as _case  # noqa: F401
import suitest_db.models.code_export as _code_export  # noqa: F401
import suitest_db.models.defect as _defect  # noqa: F401
import suitest_db.models.document as _document  # noqa: F401
import suitest_db.models.eval_run as _eval_run  # noqa: F401
import suitest_db.models.generator_run as _generator_run  # noqa: F401
import suitest_db.models.integration as _integration  # noqa: F401
import suitest_db.models.invitation as _invitation  # noqa: F401
import suitest_db.models.llm_config as _llm_config  # noqa: F401
import suitest_db.models.mcp_provider as _mcp_provider  # noqa: F401
import suitest_db.models.password_reset_request as _password_reset_request  # noqa: F401
import suitest_db.models.project as _project  # noqa: F401
import suitest_db.models.prompt_version as _prompt_version  # noqa: F401
import suitest_db.models.requirement as _requirement  # noqa: F401
import suitest_db.models.run as _run  # noqa: F401
import suitest_db.models.run_step_log as _run_step_log  # noqa: F401
import suitest_db.models.tenancy as _tenancy  # noqa: F401
import suitest_db.models.user as _user  # noqa: F401
import suitest_db.models.workspace as _workspace  # noqa: F401
import suitest_db.models.workspace_capability as _workspace_capability  # noqa: F401
