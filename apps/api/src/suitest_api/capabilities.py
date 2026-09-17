"""Assemble the public capability response from workspace configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from suitest_core.capabilities import AutonomyLevel as CoreAutonomy
from suitest_core.capabilities import (
    LlmStatus,
    compute_autonomy,
    compute_features,
    resolve_embeddings,
)
from suitest_shared.schemas.capabilities import (
    AuthSection,
    AutonomySection,
    Capabilities,
    EmbeddingsSection,
    FeaturesSection,
    LLMSection,
    McpProviderPublic,
)

from suitest_api import __version__
from suitest_api.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from suitest_db.models.llm_config import LLMConfig
    from suitest_db.models.mcp_provider import McpProvider
    from suitest_db.models.workspace_capability import WorkspaceCapability


def _features_section(features: dict[str, bool]) -> FeaturesSection:
    return FeaturesSection.model_validate(features)


def _autonomy_section(llm_ready: bool, current: CoreAutonomy | None = None) -> AutonomySection:
    info = compute_autonomy(llm_ready)
    selected = current if current in info.available else info.default
    return AutonomySection(available=list(info.available), default=selected)


def _auth_section() -> AuthSection:
    """Resolve auth capability flags from process settings (env-derived).

    Google OAuth is only advertised when BOTH the client id and secret are set —
    matching the FastAPI-Users Google client construction in the auth router.
    """
    settings = get_settings()
    google_enabled = bool(settings.oauth_google_client_id and settings.oauth_google_client_secret)
    return AuthSection(google_oauth_enabled=google_enabled)


def llm_status(config: LLMConfig | None) -> LlmStatus:
    """Return the stable readiness state used by gates, API clients, and MCP."""
    if config is None:
        return LlmStatus.NOT_CONFIGURED
    if config.last_validated_at is None:
        return LlmStatus.VALIDATION_REQUIRED
    return LlmStatus.READY


def build_base_capabilities() -> Capabilities:
    """Build the deployment base before a workspace is selected."""
    embeddings = resolve_embeddings()
    llm = LLMSection()
    return Capabilities(
        llm=llm,
        embeddings=EmbeddingsSection(
            enabled=embeddings.enabled,
            backend=embeddings.backend,
            model=embeddings.model,
            dim=embeddings.dim,
        ),
        features=_features_section(compute_features(False, embeddings)),
        autonomy=_autonomy_section(False),
        auth=_auth_section(),
        version=__version__,
        mcp_providers=[],
    )


def _mcp_public(rows: Sequence[McpProvider]) -> list[McpProviderPublic]:
    out: list[McpProviderPublic] = []
    for row in rows:
        is_default = bool(row.is_default_for_target)
        out.append(
            McpProviderPublic(
                id=row.id,
                name=row.name,
                kind=row.kind,
                health=row.health_status,
                is_default=is_default,
            )
        )
    return out


def build_workspace_overlay(
    base: Capabilities,
    *,
    workspace_capability: WorkspaceCapability | None,
    active_llm_config: LLMConfig | None,
    mcp_providers: Sequence[McpProvider],
) -> Capabilities:
    """Overlay workspace DB rows on top of the unauthenticated base.

    Features and autonomy follow a validated active LLM. ``McpProvider`` rows
    populate ``mcp_providers`` independently so Settings remains usable.
    """
    embeddings = resolve_embeddings()

    status = llm_status(active_llm_config)
    ready = status is LlmStatus.READY
    if active_llm_config is not None:
        # CAPABILITY_TIERS §11.2: workspace DB config is the source of truth. base_url
        # lives in config_json (DATA_MODEL §4.1); fall back to the base only when absent.
        config_base_url = active_llm_config.config_json.get("base_url")
        overlaid_base_url = config_base_url if isinstance(config_base_url, str) else None
        llm = LLMSection(
            status=status,
            provider=active_llm_config.provider,
            model=active_llm_config.model or None,
            base_url=overlaid_base_url if overlaid_base_url else base.llm.base_url,
            is_test_provider=active_llm_config.provider.strip().lower() == "mock",
        )
    else:
        llm = base.llm

    return Capabilities(
        llm=llm,
        embeddings=base.embeddings,
        features=_features_section(compute_features(ready, embeddings)),
        autonomy=_autonomy_section(
            ready,
            workspace_capability.autonomy_level if workspace_capability is not None else None,
        ),
        auth=base.auth,
        version=base.version,
        mcp_providers=_mcp_public(mcp_providers),
    )
