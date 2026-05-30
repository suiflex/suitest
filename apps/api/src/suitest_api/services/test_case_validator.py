"""Per-step validator shared by ``POST /test-cases`` + ``PATCH …/steps``.

Two domain rules (``docs/API.md §3.3 step validator behaviour``):

* ``STEPS_REQUIRE_CODE_IN_ZERO_LLM`` — when the workspace runs ``ZERO`` tier
  AND ``workspace.strict_zero_validation=true``, every step MUST carry a
  non-empty ``code``. Action-only steps (no ``code``) are 400 with
  ``details.stepIndex=N`` so the FE can highlight the offending row.
* ``MCP_PROVIDER_NOT_REGISTERED`` — every step's ``mcp_provider`` must be
  either a bundled builtin (``api-http-mcp``, ``playwright-mcp``,
  ``postgres-mcp``, ``jirac-mcp``, ``github-mcp-server``) OR present in the
  workspace's ``mcp_providers`` table. Unknown providers raise 404.

Both rules surface as typed exceptions so the router (and any internal caller
— ad-hoc run, autopilot) can translate them to the canonical API error
envelopes uniformly.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from suitest_shared.domain.enums import Tier

if TYPE_CHECKING:
    from suitest_api.schemas.test_case import StepAppend, StepCreate


# Bundled MCP providers that are always available even when the workspace
# has no rows in ``mcp_providers``. Kept aligned with the runner's
# :data:`suitest_api.services.run_service._BUNDLED_MCP_PROVIDERS` (the only
# two callers — keep both lists in sync).
BUNDLED_MCP_PROVIDERS: frozenset[str] = frozenset(
    {
        "api-http-mcp",
        "playwright-mcp",
        "postgres-mcp",
        "jirac-mcp",
        "github-mcp-server",
    }
)


class StepValidationError(Exception):
    """Base class for validator errors so callers can ``except`` on one type."""


class StepsRequireCodeError(StepValidationError):
    """ZERO tier + ``strict_zero_validation=true`` + step missing ``code``."""

    def __init__(self, step_index: int) -> None:
        super().__init__(
            f"step #{step_index} has no executable code; ZERO tier cannot translate "
            "action -> MCP call at runtime"
        )
        self.step_index = step_index


class McpProviderNotRegisteredError(StepValidationError):
    """Step references an MCP provider not bundled and not in ``mcp_providers``."""

    def __init__(self, name: str, step_index: int) -> None:
        super().__init__(f"MCP provider {name!r} is not registered for this workspace")
        self.name = name
        self.step_index = step_index


def validate_steps(
    steps: Sequence[StepCreate | StepAppend],
    *,
    tier: Tier,
    strict_zero_validation: bool,
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
        if tier is Tier.ZERO and strict_zero_validation and not (step.code and step.code.strip()):
            raise StepsRequireCodeError(step_index=index)
        if step.mcp_provider not in allowed:
            raise McpProviderNotRegisteredError(name=step.mcp_provider, step_index=index)
