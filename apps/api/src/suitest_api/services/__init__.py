"""Service layer — business rules + tenant scoping. Routers stay thin.

Workspace-scoped services constrain every query to ``ctx.workspace_id``;
cross-workspace access returns ``None`` (router maps to 404). MCP, run, and LLM
paths enforce workspace LLM readiness at their shared boundary.
"""
