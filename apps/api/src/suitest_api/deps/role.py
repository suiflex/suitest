"""Role-gating dependency for write endpoints (M1d-2+).

The tenant-membership dep (``require_workspace_membership``) only proves the
caller is *in* the workspace; per ``docs/API.md`` write endpoints additionally
require ``QA`` or higher (``QA`` / ``ADMIN`` / ``OWNER``). ``VIEWER`` reads
freely but cannot mutate.

Usage::

    @router.post(
        "/test-cases",
        dependencies=[Depends(require_role({Role.QA, Role.ADMIN, Role.OWNER}))],
    )
    async def create_test_case(...): ...

The factory returns a dependency closure that pulls the resolved
:class:`TenantContext` and raises ``403`` when ``ctx.role`` is not in the
allowed set. Keep it side-effect-free so ``Depends(...)`` can be reused across
routes.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from suitest_shared.domain.enums import Role

from suitest_api.deps.scope import TenantContext, require_workspace_membership


def require_role(allowed: set[Role]) -> Callable[[TenantContext], TenantContext]:
    """Return a FastAPI dependency that enforces ``ctx.role in allowed``.

    Raises ``403 Forbidden`` when the membership role is not permitted. Returns
    the :class:`TenantContext` unchanged so the handler can keep ``ctx`` typed
    via the dep chain.
    """
    frozen_allowed = frozenset(allowed)

    def _checker(
        ctx: TenantContext = Depends(require_workspace_membership),
    ) -> TenantContext:
        if ctx.role not in frozen_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role '{ctx.role.value}' is not permitted on this endpoint",
            )
        return ctx

    return _checker
