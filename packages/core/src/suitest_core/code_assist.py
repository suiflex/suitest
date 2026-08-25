"""Code Assist — the Google backends reached by signing in, not by a key.

Two products sit on the same protocol, and Suitest treats them as one adapter
with a variant table rather than two implementations:

* **Gemini Code Assist**, what the Gemini CLI talks to.
* **Antigravity**, Google's agentic IDE. Same OAuth, same onboarding calls, its
  own client registration, two extra scopes, and a different serving host.

The point of this path is that it asks the user for nothing. Vertex needs a GCP
project because its endpoint is built from one; here ``load_code_assist``
discovers the project the account already has, and ``onboard_user`` provisions
one when it does not. That is why signing in to the Gemini CLI never asks.

Neither endpoint is a documented public API. They are the surface these vendors'
own clients use, reached with those clients' credentials — the same standing as
the ChatGPT backend in :mod:`suitest_core.chatgpt_oauth`, and the reason the UI
carries a risk notice.

Wire format, for the provider that has to build it::

    POST {api_endpoint}/v1internal:generateContent
    POST {api_endpoint}/v1internal:streamGenerateContent?alt=sse
    {"project": "...", "model": "...", "request": {<GenerateContentRequest>}}

Antigravity adds ``userAgent``/``requestType`` alongside ``project``; those live
in :attr:`CodeAssistVariant.envelope_extra` so the provider stays variant-blind.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel

from suitest_core.google_oauth import DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET

if TYPE_CHECKING:
    import httpx

#: Provider key for Gemini Code Assist, what the Gemini CLI reaches.
CODE_ASSIST_PROVIDER: Final = "google-codeassist"
#: Provider key for Antigravity, Google's agentic IDE.
ANTIGRAVITY_PROVIDER: Final = "antigravity"

_LOAD_PATH: Final = "/v1internal:loadCodeAssist"
_ONBOARD_PATH: Final = "/v1internal:onboardUser"
_MODELS_PATH: Final = "/v1internal:fetchAvailableModels"
#: Onboarding is a long-running operation; poll it rather than assume it is done.
_ONBOARD_ATTEMPTS: Final = 10
_ONBOARD_INTERVAL_S: Final = 5.0
_DEFAULT_TIER: Final = "legacy-tier"

#: Where onboarding is driven from, for both variants.
CLOUDCODE_ENDPOINT: Final = "https://cloudcode-pa.googleapis.com"

# Antigravity's client is deliberately NOT bundled, unlike the Gemini CLI's.
#
# The difference is provenance, not shape. Google publishes the Gemini CLI's
# client in its own repository with a comment saying it is fine to keep in git.
# Nothing comparable exists for Antigravity: its client is only known because a
# third party read it out of the IDE, so shipping it would be redistributing
# someone else's reverse-engineering under Suitest's name.
#
# An operator who wants this provider supplies the pair themselves via
# ``SUITEST_LLM_ANTIGRAVITY_OAUTH_CLIENT_ID`` / ``_SECRET``; the sign-in refuses
# with ``OAUTH_CLIENT_UNSET`` until they do.


class CodeAssistError(Exception):
    """A Code Assist onboarding step failed. ``code`` is the API-facing code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CodeAssistVariant:
    """One product on the Code Assist protocol.

    ``api_endpoint`` is where completions go; onboarding always runs against
    :data:`CLOUDCODE_ENDPOINT`, which is shared.
    """

    provider: str
    client_id: str
    client_secret: str
    scopes: tuple[str, ...]
    api_endpoint: str
    user_agent: str
    #: Envelope fields this variant sends beside ``project`` and ``model``.
    envelope_extra: dict[str, str] = field(default_factory=dict)
    #: ``ideType`` in the onboarding metadata, identifying the calling client.
    ide_type: int = 9


_GOOGLE_SCOPES: Final = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)

CODE_ASSIST_VARIANTS: Final[dict[str, CodeAssistVariant]] = {
    CODE_ASSIST_PROVIDER: CodeAssistVariant(
        provider=CODE_ASSIST_PROVIDER,
        # The same Gemini CLI client the Vertex sign-in uses.
        client_id=DEFAULT_CLIENT_ID,
        client_secret=DEFAULT_CLIENT_SECRET,
        scopes=_GOOGLE_SCOPES,
        api_endpoint=CLOUDCODE_ENDPOINT,
        user_agent="GeminiCLI/1.0.0 (suitest)",
    ),
    ANTIGRAVITY_PROVIDER: CodeAssistVariant(
        provider=ANTIGRAVITY_PROVIDER,
        client_id="",
        client_secret="",
        # Antigravity asks for two scopes the Gemini CLI does not.
        scopes=(
            *_GOOGLE_SCOPES,
            "https://www.googleapis.com/auth/cclog",
            "https://www.googleapis.com/auth/experimentsandconfigs",
        ),
        # Its own serving host; onboarding still runs against cloudcode-pa.
        api_endpoint="https://daily-cloudcode-pa.googleapis.com",
        user_agent="antigravity-cockpit-tools",
        envelope_extra={"userAgent": "antigravity", "requestType": "agent"},
    ),
}


class CodeAssistAccount(BaseModel):
    """What onboarding settled on: the project to bill, and the tier allowed."""

    project_id: str
    tier_id: str = _DEFAULT_TIER


def variant(provider: str) -> CodeAssistVariant:
    """Return the variant for ``provider``, or raise if it has none."""
    found = CODE_ASSIST_VARIANTS.get(provider.strip().lower())
    if found is None:
        raise CodeAssistError("UNKNOWN_VARIANT", f"no Code Assist variant for {provider!r}")
    return found


def client_metadata(spec: CodeAssistVariant) -> dict[str, int]:
    """The ``ClientMetadata`` the onboarding calls identify the caller with.

    ``platform`` is a numeric enum in the vendor's own protobuf; the mapping
    below is the one its clients use. An unrecognised host reports ``0``, which
    the endpoint accepts.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"}
    if system == "darwin":
        platform_enum = 2 if arm else 1
    elif system == "linux":
        platform_enum = 4 if arm else 3
    elif system == "windows":
        platform_enum = 5
    else:
        platform_enum = 0
    return {"ideType": spec.ide_type, "platform": platform_enum, "pluginType": 2}


def _headers(access_token: str, spec: CodeAssistVariant) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": spec.user_agent,
        "x-request-source": "local",
    }


def _project_of(raw: object) -> str | None:
    """``cloudaicompanionProject`` is sometimes a string, sometimes an object."""
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict):
        value = raw.get("id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def load_code_assist(
    client: httpx.AsyncClient,
    *,
    access_token: str,
    spec: CodeAssistVariant,
    endpoint: str = CLOUDCODE_ENDPOINT,
) -> tuple[str | None, str]:
    """Return ``(project_id, tier_id)`` for the signed-in account.

    ``project_id`` is ``None`` when the account has no Code Assist project yet;
    :func:`onboard_user` provisions one.
    """
    response = await client.post(
        f"{endpoint.rstrip('/')}{_LOAD_PATH}",
        headers=_headers(access_token, spec),
        json={"metadata": client_metadata(spec)},
    )
    if response.status_code >= 400:
        raise CodeAssistError(
            "LOAD_FAILED", f"loadCodeAssist returned status {response.status_code}"
        )
    try:
        parsed = response.json()
    except ValueError as exc:
        raise CodeAssistError("BAD_RESPONSE", "loadCodeAssist returned non-JSON") from exc
    body: dict[str, object] = parsed if isinstance(parsed, dict) else {}

    tier_id = _DEFAULT_TIER
    tiers = body.get("allowedTiers")
    if isinstance(tiers, list):
        for tier in tiers:
            if isinstance(tier, dict) and tier.get("isDefault") and isinstance(tier.get("id"), str):
                tier_id = str(tier["id"]).strip()
                break

    return _project_of(body.get("cloudaicompanionProject")), tier_id


async def onboard_user(
    client: httpx.AsyncClient,
    *,
    access_token: str,
    spec: CodeAssistVariant,
    tier_id: str = _DEFAULT_TIER,
    endpoint: str = CLOUDCODE_ENDPOINT,
    attempts: int = _ONBOARD_ATTEMPTS,
    sleep_s: float = _ONBOARD_INTERVAL_S,
) -> str:
    """Provision a Code Assist project and return its id.

    A long-running operation: the first call usually answers ``done: false``, so
    it is re-issued until it settles. Treating the first reply as final is what
    would hand back an empty project id and fail at the first completion.
    """
    import asyncio

    for attempt in range(attempts):
        response = await client.post(
            f"{endpoint.rstrip('/')}{_ONBOARD_PATH}",
            headers=_headers(access_token, spec),
            json={"tierId": tier_id, "metadata": client_metadata(spec)},
        )
        if response.status_code >= 400:
            raise CodeAssistError(
                "ONBOARD_FAILED", f"onboardUser returned status {response.status_code}"
            )
        try:
            parsed = response.json()
        except ValueError as exc:
            raise CodeAssistError("BAD_RESPONSE", "onboardUser returned non-JSON") from exc
        body: dict[str, object] = parsed if isinstance(parsed, dict) else {}

        if body.get("done") is True:
            inner = body.get("response")
            project = _project_of(
                inner.get("cloudaicompanionProject") if isinstance(inner, dict) else None
            )
            if project is None:
                raise CodeAssistError(
                    "ONBOARD_NO_PROJECT", "onboarding finished without naming a project"
                )
            return project

        if attempt + 1 < attempts:
            await asyncio.sleep(sleep_s)

    raise CodeAssistError("ONBOARD_TIMEOUT", "onboarding did not finish; sign in again")


async def resolve_account(
    client: httpx.AsyncClient,
    *,
    access_token: str,
    spec: CodeAssistVariant,
    endpoint: str = CLOUDCODE_ENDPOINT,
    sleep_s: float = _ONBOARD_INTERVAL_S,
) -> CodeAssistAccount:
    """Discover the account's project, provisioning one if it has none."""
    project_id, tier_id = await load_code_assist(
        client, access_token=access_token, spec=spec, endpoint=endpoint
    )
    if project_id is None:
        project_id = await onboard_user(
            client,
            access_token=access_token,
            spec=spec,
            tier_id=tier_id,
            endpoint=endpoint,
            sleep_s=sleep_s,
        )
    return CodeAssistAccount(project_id=project_id, tier_id=tier_id)


async def fetch_available_models(
    client: httpx.AsyncClient,
    *,
    access_token: str,
    spec: CodeAssistVariant,
    endpoint: str = CLOUDCODE_ENDPOINT,
) -> list[str]:
    """List the model ids this account may call, newest surface first.

    Returns ``[]`` rather than raising: a sign-in that already succeeded must
    not fail because its model list could not be read, and the caller falls
    back to letting the user type one.

    The response shape is not documented anywhere public. Model entries have
    been seen keyed by ``name`` and by ``modelId``, so both are accepted and
    anything unrecognised is skipped rather than guessed at.
    """
    import httpx as _httpx

    try:
        response = await client.post(
            f"{endpoint.rstrip('/')}{_MODELS_PATH}",
            headers=_headers(access_token, spec),
            json={"metadata": client_metadata(spec)},
        )
    except _httpx.HTTPError:
        return []
    if response.status_code >= 400:
        return []
    try:
        parsed = response.json()
    except ValueError:
        return []
    if not isinstance(parsed, dict):
        return []

    models: list[str] = []
    for raw in parsed.get("models") or []:
        if isinstance(raw, str) and raw.strip():
            models.append(raw.strip())
            continue
        if not isinstance(raw, dict):
            continue
        for key in ("modelId", "name", "model"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                # Some surfaces qualify the id as "models/<id>".
                models.append(value.strip().removeprefix("models/"))
                break
    # Preserve order while dropping repeats: the same model can appear under
    # more than one entry.
    return list(dict.fromkeys(models))
