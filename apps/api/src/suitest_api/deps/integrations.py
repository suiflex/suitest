"""FastAPI dependency: shared :class:`AdapterRegistry`.

The registry is constructed at import time as a process-wide singleton in
:mod:`suitest_api.integrations.registry` and stashed on
``app.state.adapter_registry`` by the lifespan (``main.py``). This dependency
returns it so request handlers don't reach into ``request.app.state``
directly — which is the canonical FastAPI DI pattern documented in
``CLAUDE.md §2.3`` ("dependency injection via ``Depends``").

Tests can override the dependency with
``app.dependency_overrides[get_adapter_registry] = lambda: my_registry`` to
inject a per-test :class:`AdapterRegistry` without mutating the module-level
singleton.
"""

from __future__ import annotations

from fastapi import Request

from suitest_api.integrations.registry import AdapterRegistry, adapter_registry


def get_adapter_registry(request: Request) -> AdapterRegistry:
    """Return the :class:`AdapterRegistry` stashed on ``app.state.adapter_registry``.

    Falls back to the module-level singleton if the lifespan hasn't populated
    ``app.state`` yet (e.g. tests that construct the app without entering the
    lifespan). The singleton is always safe to return because registrations
    happen at startup before any request lands.
    """
    stashed = getattr(request.app.state, "adapter_registry", None)
    if isinstance(stashed, AdapterRegistry):
        return stashed
    return adapter_registry
