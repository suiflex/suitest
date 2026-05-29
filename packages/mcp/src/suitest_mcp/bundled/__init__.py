"""In-process server builders for bundled providers (api-http, postgres, ...).

Importing this package registers every bundled provider's builder with the
in-process runtime registry so :func:`suitest_mcp.client.open_session` can
resolve them by name (``api-http-mcp``, ``postgres-mcp``, ...).
"""

from __future__ import annotations

from suitest_mcp.bundled.api_http import ApiHttpServer, build_api_http_server
from suitest_mcp.bundled.in_process_runtime import register_bundled_builder

# Registration is module-level so it happens exactly once at import time. The
# generic client lazy-imports ``in_process_runtime``, which transitively imports
# this package, which registers the bundled builders. Custom providers can call
# :func:`register_bundled_builder` themselves to extend the registry.
register_bundled_builder("api-http-mcp", build_api_http_server)

__all__ = ["ApiHttpServer", "build_api_http_server"]
