"""Turn the workspace's active ``LLMConfig`` into a ready LLM provider.

Thin wrapper over :mod:`suitest_core.llm_credentials`: that module decides what a
stored credential means, this one supplies the HTTP client, persists a refreshed
token set, and hands back a provider. Call sites should never read
``api_key_encrypted`` or dig ``base_url`` out of ``config_json`` themselves —
a Sign in with ChatGPT config has neither.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from suitest_agent.providers.litellm_router import get_provider
from suitest_core.llm_credentials import ResolvedCredential, resolve_credential
from suitest_db.repositories.llm_configs import LLMConfigRepo, LLMConfigUpdate

from suitest_api.settings import get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_agent.providers.base import LLMProvider
    from suitest_db.models.llm_config import LLMConfig

_REFRESH_TIMEOUT = 30.0


async def resolve_for_config(session: AsyncSession, config: LLMConfig) -> ResolvedCredential:
    """Resolve ``config`` into call arguments, refreshing its tokens if due.

    A refreshed token set is written back before returning, so the next caller
    does not repeat the round trip.
    """
    async with httpx.AsyncClient(timeout=_REFRESH_TIMEOUT) as client:
        credential, persist = await resolve_credential(
            client,
            provider=config.provider,
            api_key=config.api_key_encrypted,
            base_url=config.base_url,
            oauth_tokens_json=config.oauth_tokens_encrypted,
            client_id=get_settings().chatgpt_oauth_client_id,
        )
    if persist is not None:
        await LLMConfigRepo(session).update(
            config.id, LLMConfigUpdate(oauth_tokens_encrypted=persist)
        )
        await session.commit()
    return credential


async def provider_for_config(session: AsyncSession, config: LLMConfig) -> LLMProvider:
    """Resolve ``config`` and build the provider for it."""
    credential = await resolve_for_config(session, config)
    return provider_for_credential(credential)


def provider_for_credential(credential: ResolvedCredential) -> LLMProvider:
    """Build a provider from an already-resolved credential.

    For call paths that resolve at the router and hand the pieces down.
    """
    return get_provider(
        credential.provider,
        api_key=credential.api_key,
        base_url=credential.base_url,
        extra_headers=credential.extra_headers or None,
    )
