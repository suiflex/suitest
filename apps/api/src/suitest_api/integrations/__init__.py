"""Issue-tracker integration adapter package.

Per the project ``CLAUDE.md`` rule "no barrel files", this ``__init__`` only
re-exports the process-wide :data:`adapter_registry` singleton — the one
attribute that production callers (``apps/api/src/suitest_api/main.py``
lifespan, ``IntegrationService.sync_external``) need to import without
reaching deeper. Everything else (Protocol, DTOs, errors, registry class)
must be imported from its concrete submodule (``base.py`` / ``registry.py`` /
``contract.py``).
"""

from __future__ import annotations

from suitest_api.integrations.registry import adapter_registry

__all__ = ["adapter_registry"]
