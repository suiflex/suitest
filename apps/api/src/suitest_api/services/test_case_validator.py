"""Per-step MCP provider validator shared by test-case writes.

Every step's ``mcp_provider`` must be
  either a bundled builtin (``api-http-mcp``, ``playwright-mcp``,
  ``postgres-mcp``, ``jirac-mcp``, ``github-mcp-server``) OR present in the
  workspace's ``mcp_providers`` table. Unknown providers raise 404.

Both rules surface as typed exceptions so the router (and any internal caller
— ad-hoc run, autopilot) can translate them to the canonical API error
envelopes uniformly.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from suitest_mcp.providers.builtin_specs import BUILTIN_SPECS


class _StepLike(Protocol):
    """Structural type the validator needs — both Pydantic DTOs + the SQLAlchemy
    :class:`TestStep` ORM row satisfy this shape, so the M1d-8 ad-hoc run
    pre-flight can re-run validation over already-persisted rows without an
    extra DTO hop.
    """

    @property
    def mcp_provider(self) -> str: ...


# MCP providers a step may name even when the workspace has no rows in
# ``mcp_providers``: every builtin (the registry seeds those per workspace)
# plus the integration servers that ship outside the spec list.
#
# Derived, not hand-listed. This used to be a literal frozenset duplicated in
# ``run_service``, with a comment asking both copies to be kept in sync — by
# the time the desktop providers landed the two had already drifted apart (5
# names here, 3 there), so a step naming a real builtin was rejected as
# unregistered. ``run_service`` imports this now; there is one list.
_EXTRA_MCP_PROVIDERS: frozenset[str] = frozenset({"jirac-mcp", "github-mcp-server"})

BUNDLED_MCP_PROVIDERS: frozenset[str] = frozenset(
    {spec.name for spec in BUILTIN_SPECS} | _EXTRA_MCP_PROVIDERS
)


class StepValidationError(Exception):
    """Base class for validator errors so callers can ``except`` on one type."""


class McpProviderNotRegisteredError(StepValidationError):
    """Step references an MCP provider not bundled and not in ``mcp_providers``."""

    def __init__(self, name: str, step_index: int) -> None:
        super().__init__(f"MCP provider {name!r} is not registered for this workspace")
        self.name = name
        self.step_index = step_index


def validate_steps(
    steps: Sequence[_StepLike],
    *,
    registered_mcp_names: set[str],
) -> None:
    """Validate every step in order; raise on the first failure.

    The first failure is sufficient — the FE rejects-on-first-error UI shows
    one inline marker per submit cycle. Surfacing every error at once would
    require a richer error envelope shape not specified in
    ``docs/API.md``; keep this behaviour parallel to the runner's create-run
    validator (one error per submit).
    """
    allowed = set(registered_mcp_names) | BUNDLED_MCP_PROVIDERS
    for index, step in enumerate(steps):
        if step.mcp_provider not in allowed:
            raise McpProviderNotRegisteredError(name=step.mcp_provider, step_index=index)
