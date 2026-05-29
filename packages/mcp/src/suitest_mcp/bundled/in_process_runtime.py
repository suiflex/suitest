"""In-process MCP server runtime (M1c Task 6 — bundled api-http/postgres).

Real builders ship in Task 6 / Task 8. This module currently exposes a stub
:func:`in_process_client` so the generic client (:mod:`suitest_mcp.client`) can
type-check against :data:`McpTransport.IN_PROCESS` before bundled providers
land. Calling the stub raises so a misconfigured provider fails loudly.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from suitest_mcp.models import McpProviderConfig


@contextlib.asynccontextmanager
async def in_process_client(
    provider: McpProviderConfig,
) -> AsyncIterator[tuple[Any, Any]]:
    """Placeholder — real builders ship in M1c Task 6 / Task 8."""
    raise NotImplementedError(f"in-process transport for {provider.name!r} not implemented yet")
    yield  # pragma: no cover — keeps the function a generator for the decorator
