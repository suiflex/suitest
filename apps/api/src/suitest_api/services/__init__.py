"""Service layer — business rules + tenant scoping. Routers stay thin.

Every public service method is decorated with ``@require_tier(...)`` (no-op in
M1a, enforced in M3). Workspace-scoped services constrain every query to
``ctx.workspace_id``; cross-workspace access returns ``None`` (router maps to 404).
"""
