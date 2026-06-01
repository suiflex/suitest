"""In-process MCP server runtime (M1c Task 6 / Task 8 — bundled providers).

Bundled providers (api-http-mcp, postgres-mcp) run inside the Suitest process
instead of spawning a subprocess: client and server share a pair of in-memory
``anyio`` object streams. This file owns:

* The :class:`BundledServer` :class:`~typing.Protocol` every bundled provider
  implements — a thin shape with ``list_tools`` / ``call_tool`` so transport
  glue here can dispatch without importing concrete server classes.
* :data:`BUNDLED_BUILDERS` — name-keyed registry mapping
  :attr:`McpProviderConfig.name` to a factory that returns a fresh
  :class:`BundledServer`. Concrete providers register themselves here
  (``postgres-mcp`` lives in :mod:`suitest_mcp.bundled.postgres`; api-http lands
  in Task 6 / :mod:`suitest_mcp.bundled.api_http`).
* :func:`in_process_client` — the async context manager
  :func:`suitest_mcp.client._transport_context` opens for
  :attr:`McpTransport.IN_PROCESS`. It builds the named server, wires it up to a
  background ``mcp.Server.run`` task driven by an :class:`mcp.server.Server`
  shim, and yields ``(read_stream, write_stream)`` for the client side.

The shim path keeps the bundled provider implementation decoupled from the
``mcp`` SDK's :class:`~mcp.server.Server` decorator gymnastics — providers just
implement the protocol and we adapt it into an :class:`~mcp.server.Server`
inside this module.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, Protocol

import anyio
from mcp.server import Server
from mcp.shared.memory import create_client_server_memory_streams

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from mcp.types import TextContent, Tool

    from suitest_mcp.models import McpProviderConfig


class BundledServer(Protocol):
    """Shape every bundled in-process server implements.

    Each method returns the *unwrapped* domain payload — the runtime adapts
    them onto the :class:`mcp.server.Server` decorator surface so providers do
    not have to depend on the SDK directly.
    """

    async def list_tools(self) -> list[Tool]:
        """Return the tool catalog advertised over ``tools/list``."""
        ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Dispatch a tool invocation and return MCP content blocks."""
        ...

    async def aclose(self) -> None:
        """Release provider-owned resources (pools, sockets, ...).

        Called when the in-process session is torn down. Implementations
        may be no-ops if there is nothing to release.
        """
        ...


_BUILDERS: dict[str, Callable[[McpProviderConfig], BundledServer]] = {}


#: Map of provider name -> module path to lazy-import when the registry misses.
#: Lets the runtime resolve builtins without forcing the bundled subpackage's
#: ``__init__`` to import every provider eagerly (which would drag heavy deps
#: like ``psycopg``/``httpx`` into the import graph even when unused).
_LAZY_MODULES: dict[str, str] = {
    "postgres-mcp": "suitest_mcp.bundled.postgres",
    "api-http-mcp": "suitest_mcp.bundled.api_http",
    # M2-10 additive bundled providers.
    "graphql-mcp": "suitest_mcp.bundled.graphql",
    "mysql-mcp": "suitest_mcp.bundled.mysql",
    "mongo-mcp": "suitest_mcp.bundled.mongo",
    "kubernetes-mcp": "suitest_mcp.bundled.kubernetes",
    "grpc-mcp": "suitest_mcp.bundled.grpc",
}


def register_bundled_builder(
    name: str, builder: Callable[[McpProviderConfig], BundledServer]
) -> None:
    """Register ``builder`` as the factory for the bundled provider ``name``.

    Idempotent re-registration overrides the previous entry — useful for tests
    that want to swap a real bundled provider for a fake without touching the
    builtin spec list.
    """
    _BUILDERS[name] = builder


def get_bundled_builder(name: str) -> Callable[[McpProviderConfig], BundledServer]:
    """Look up a previously registered bundled builder by ``name``.

    Falls back to importing the matching module from :data:`_LAZY_MODULES`
    (which triggers its module-level :func:`register_bundled_builder` call) so
    callers do not have to remember to import bundled provider modules before
    opening a session.

    Raises:
        KeyError: no bundled builder registered for ``name`` and no lazy module
            path is known.
    """
    builder = _BUILDERS.get(name)
    if builder is not None:
        return builder
    module_path = _LAZY_MODULES.get(name)
    if module_path is None:
        raise KeyError(name)
    import importlib

    importlib.import_module(module_path)
    return _BUILDERS[name]


def _adapt_server(server: BundledServer, label: str) -> Server[object, object]:
    """Wrap a :class:`BundledServer` in an :class:`mcp.server.Server`.

    The SDK requires its decorator-based handler registration, so we mount the
    bundled provider's coroutines onto a fresh ``Server`` instance per session.
    """
    app: Server[object, object] = Server(label)

    @app.list_tools()  # type: ignore[no-untyped-call,misc,untyped-decorator,unused-ignore]
    async def _list_tools() -> list[Tool]:
        return await server.list_tools()

    @app.call_tool()  # type: ignore[no-untyped-call,misc,untyped-decorator,unused-ignore]
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        return await server.call_tool(name, arguments)

    return app


@contextlib.asynccontextmanager
async def in_process_client(
    provider: McpProviderConfig,
) -> AsyncIterator[tuple[Any, Any]]:
    """Yield client-side ``(read, write)`` streams connected to a bundled server.

    Resolves the bundled builder via :func:`get_bundled_builder` keyed on
    :attr:`McpProviderConfig.name`. Spawns the :class:`mcp.server.Server` on a
    background ``anyio`` task using a pair of in-memory streams from
    :func:`mcp.shared.memory.create_client_server_memory_streams`. On exit the
    server task is cancelled and :meth:`BundledServer.aclose` is awaited.
    """
    try:
        builder = get_bundled_builder(provider.name)
    except KeyError as exc:
        raise NotImplementedError(
            f"in-process transport for {provider.name!r} not implemented yet"
        ) from exc

    bundled = builder(provider)
    app = _adapt_server(bundled, provider.name)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:

            async def _run_server() -> None:
                # ``raise_exceptions=True`` makes assertion / programming errors
                # visible immediately in tests instead of being swallowed as
                # ``isError=true`` content; the client layer surfaces them as
                # :class:`McpToolFailed` either way.
                await app.run(
                    server_read,
                    server_write,
                    app.create_initialization_options(),
                    raise_exceptions=False,
                )

            tg.start_soon(_run_server)
            try:
                yield client_streams
            finally:
                tg.cancel_scope.cancel()
                with contextlib.suppress(Exception):
                    await bundled.aclose()
