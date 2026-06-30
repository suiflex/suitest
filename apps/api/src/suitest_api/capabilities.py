"""Assemble the public :class:`Capabilities` response from the ZERO base + overlay.

Two builders:

* :func:`build_base_capabilities` — the ZERO deployment base (no env, no LLM),
  called once at startup and stashed on ``app.state.capabilities``.
* :func:`build_workspace_overlay` — layers a workspace ``WorkspaceCapability`` +
  active ``LLMConfig`` + ``McpProvider`` rows on top of the base, per
  docs/CAPABILITY_TIERS.md §11.2 precedence (workspace ``LLMConfig`` > base). The
  per-workspace LLM provider (set from the web UI) is what raises the tier.

The lower-level tier/feature/autonomy primitives live in
``suitest_core.capabilities``; these builders only wire them into the wire schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from suitest_core.capabilities import (
    Tier,
    compute_autonomy,
    compute_features,
    resolve_embeddings,
    resolve_tier,
)
from suitest_shared.domain.enums import Tier as SharedTier
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

_LOCAL_PROVIDERS = frozenset({"ollama", "llamacpp", "vllm", "lmstudio"})


def _features_section(features: dict[str, bool]) -> FeaturesSection:
    return FeaturesSection.model_validate(features)


def _autonomy_section(tier: Tier) -> AutonomySection:
    info = compute_autonomy(tier)
    return AutonomySection(available=list(info.available), default=info.default)


def _auth_section() -> AuthSection:
    """Resolve auth capability flags from process settings (env-derived).

    Google OAuth is only advertised when BOTH the client id and secret are set —
    matching the FastAPI-Users Google client construction in the auth router.
    """
    settings = get_settings()
    google_enabled = bool(settings.oauth_google_client_id and settings.oauth_google_client_secret)
    return AuthSection(google_oauth_enabled=google_enabled)


def build_base_capabilities() -> Capabilities:
    """Build the ZERO deployment base (no env, no LLM).

    LLM/embeddings are configured per-workspace from the web UI; the base is
    unconditionally ZERO and :func:`build_workspace_overlay` raises the effective
    tier from the workspace's active ``LLMConfig``.
    """
    tier = resolve_tier()
    embeddings = resolve_embeddings()
    llm = LLMSection(provider="none", model=None, base_url=None, is_test_provider=False)
    return Capabilities(
        tier=SharedTier(tier.value),
        llm=llm,
        embeddings=EmbeddingsSection(
            enabled=embeddings.enabled,
            backend=embeddings.backend,
            model=embeddings.model,
            dim=embeddings.dim,
        ),
        features=_features_section(compute_features(tier, embeddings)),
        autonomy=_autonomy_section(tier),
        auth=_auth_section(),
        version=__version__,
        mcp_providers=[],
    )


def _provider_to_tier(provider: str) -> Tier:
    """Map a workspace ``LLMConfig.provider`` string to the resolved tier.

    The DB-stored config is trusted (admin set it via Settings → LLM); we do not
    re-validate key presence here (that happened at save time). ``none`` / empty
    means ZERO.
    """
    p = provider.strip().lower()
    if p in {"", "none", "disabled"}:
        return Tier.ZERO
    if p in _LOCAL_PROVIDERS:
        return Tier.LOCAL
    return Tier.CLOUD


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
    """Overlay workspace DB rows on top of ``base`` (CAPABILITY_TIERS §11.2).

    Tier precedence: active ``LLMConfig.provider`` > ``WorkspaceCapability.tier`` >
    ZERO base. Features/autonomy are recomputed for the effective tier (embeddings
    follow the ZERO base). ``McpProvider`` rows populate ``mcp_providers``.
    """
    embeddings = resolve_embeddings()

    if active_llm_config is not None:
        tier = _provider_to_tier(active_llm_config.provider)
        # CAPABILITY_TIERS §11.2: workspace DB config is the source of truth. base_url
        # lives in config_json (DATA_MODEL §4.1); fall back to the base only when absent.
        config_base_url = active_llm_config.config_json.get("base_url")
        overlaid_base_url = config_base_url if isinstance(config_base_url, str) else None
        llm = LLMSection(
            provider=active_llm_config.provider,
            model=active_llm_config.model or None,
            base_url=overlaid_base_url if overlaid_base_url else base.llm.base_url,
            is_test_provider=active_llm_config.provider.strip().lower() == "mock",
        )
    elif workspace_capability is not None:
        tier = Tier(workspace_capability.tier.value)
        llm = base.llm
    else:
        tier = Tier(base.tier.value)
        llm = base.llm

    return Capabilities(
        tier=SharedTier(tier.value),
        llm=llm,
        embeddings=base.embeddings,
        features=_features_section(compute_features(tier, embeddings)),
        autonomy=_autonomy_section(tier),
        auth=base.auth,
        version=base.version,
        mcp_providers=_mcp_public(mcp_providers),
    )
