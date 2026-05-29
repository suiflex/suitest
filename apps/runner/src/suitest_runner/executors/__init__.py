"""Per-step executors for the runner.

The single executor exposed today is :func:`execute_step`, which dispatches one
:class:`suitest_db.models.case.TestStep` to the appropriate MCP provider via the
shared :class:`suitest_mcp.invoker.McpInvoker`. Future executors (M3 agentic
translator, M4 self-healing replay) will be siblings under this package.
"""
