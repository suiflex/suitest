"""Sign in with Google — OAuth protocol helpers for Google's auth endpoints.

Unlike :mod:`suitest_core.chatgpt_oauth`, everything here is public and
documented: Google's "OAuth 2.0 for iOS & Desktop Apps" installed-app flow
(https://developers.google.com/identity/protocols/oauth2/native-app).

Three things about it differ from the ChatGPT flow and drive the shape below.

**No device-code fallback.** Google does run a device flow, but it is allowed
only for the ``openid``/``email``/``profile``, Drive and YouTube scopes —
``cloud-platform`` is not on the list, so a Suitest deployment the user cannot
reach on loopback cannot use it. :func:`parse_callback_url` is the fallback
instead: the browser lands on a ``127.0.0.1`` URL nothing is listening on, and
the user pastes the address bar back into Suitest.

**Any loopback port.** A Desktop-app client accepts ``http://127.0.0.1:<port>``
without registering each port, so the listener can take an ephemeral one. That
is why there is no equivalent of ``CALLBACK_PORTS`` here.

**A client secret that is not secret.** Google issues one for Desktop-app
clients and its own documentation says the client "cannot keep the
``client_secret`` confidential" — PKCE is what actually secures the flow. It is
still required in the token request, so it is threaded through as a plain
argument.

The bundled default is the Gemini CLI's own client (``google-gemini/gemini-cli``,
Apache-2.0), which is what makes Sign in with Google work without the operator
registering anything — the same arrangement as the Codex client id in
:mod:`suitest_core.chatgpt_oauth`. An operator who would rather use a client of
their own overrides both halves in ``suitest_api.settings``.

This module is pure protocol: no database, no FastAPI, and the caller owns the
``httpx.AsyncClient`` (and therefore timeouts, proxies and test transports).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from urllib.parse import parse_qs, urlencode, urlparse

from pydantic import BaseModel

from suitest_core.oauth import OAuthError, OAuthTokens

if TYPE_CHECKING:
    import httpx

AUTH_ENDPOINT: Final = "https://accounts.google.com/o/oauth2/v2/auth"
PROJECTS_ENDPOINT: Final = "https://cloudresourcemanager.googleapis.com/v1/projects"
TOKEN_ENDPOINT: Final = "https://oauth2.googleapis.com/token"

#: Gemini CLI's public Desktop-app client (``packages/core/src/code_assist/oauth2.ts``).
DEFAULT_CLIENT_ID: Final = (
    "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
)
# Its paired secret. Not a credential in the usual sense: Google's own docs say
# that for an installed application "the client secret is obviously not treated
# as a secret", and PKCE is what actually secures this flow. gemini-cli ships it
# in source for the same reason. pragma: allowlist secret
DEFAULT_CLIENT_SECRET: Final = "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"

#: Scopes for calling Google Cloud APIs as the signed-in user, plus identity.
CLOUD_PLATFORM_SCOPES: Final = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
)

_FORM: Final = {"Content-Type": "application/x-www-form-urlencoded"}
#: Stop paging long before an account with thousands of projects stalls a request.
_MAX_PROJECT_PAGES: Final = 10


class GoogleOAuthError(OAuthError):
    """A step of the Google OAuth flow failed."""


class GoogleProject(BaseModel):
    """A GCP project the signed-in user can see."""

    project_id: str
    name: str


def loopback_redirect_uri(port: int) -> str:
    """Redirect URI for the loopback flow on an already-bound port.

    A Desktop-app client accepts any port on the loopback address, so this
    validates nothing — the literal IP is used rather than ``localhost``
    because some client firewalls block the resolved name.
    """
    if not 1 <= port <= 65535:
        raise GoogleOAuthError("BAD_PORT", f"{port} is not a usable TCP port")
    return f"http://127.0.0.1:{port}"


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    scopes: tuple[str, ...] = CLOUD_PLATFORM_SCOPES,
    endpoint: str = AUTH_ENDPOINT,
) -> str:
    """Build the consent URL the user's browser has to open.

    ``access_type=offline`` with ``prompt=consent`` is what makes Google return
    a refresh token. Without the forced prompt it only issues one on the very
    first consent, so a user who has signed in before would come back with an
    access token that expires in an hour and no way to renew it.
    """
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{endpoint}?{query}"


def parse_callback_url(url: str, *, expected_state: str) -> str:
    """Return the authorization code from a callback URL the user pasted.

    The fallback for a Suitest the browser cannot reach on loopback. Google
    reports a refusal in the query string rather than by status code, so a
    denied consent arrives here and not at the token endpoint.
    """
    query = parse_qs(urlparse(url.strip()).query)

    error = query.get("error", [None])[0]
    if error:
        raise GoogleOAuthError("CONSENT_DENIED", f"Google returned {error!r}")

    state = query.get("state", [None])[0]
    if state != expected_state:
        raise GoogleOAuthError("STATE_MISMATCH", "the pasted URL belongs to a different sign-in")

    code = query.get("code", [None])[0]
    if not code:
        raise GoogleOAuthError("NO_CODE", "the pasted URL carries no authorization code")
    return code


async def exchange_code(
    client: httpx.AsyncClient,
    *,
    client_id: str,
    client_secret: str | None,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    endpoint: str = TOKEN_ENDPOINT,
) -> OAuthTokens:
    """Trade an authorization code for tokens."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    if client_secret:
        form["client_secret"] = client_secret
    response = await client.post(endpoint, headers=_FORM, content=urlencode(form))
    return _tokens_or_raise(response, "CODE_EXCHANGE_FAILED")


async def refresh_tokens(
    client: httpx.AsyncClient,
    *,
    client_id: str,
    client_secret: str | None = None,
    refresh_token: str,
    endpoint: str = TOKEN_ENDPOINT,
) -> OAuthTokens:
    """Refresh an expiring access token.

    Google does not reissue the refresh token, so the response carries only a
    new access token — the caller keeps the one it already stored.
    """
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        form["client_secret"] = client_secret
    response = await client.post(endpoint, headers=_FORM, content=urlencode(form))
    return _tokens_or_raise(response, "REFRESH_FAILED")


def _tokens_or_raise(response: httpx.Response, code: str) -> OAuthTokens:
    if response.status_code >= 400:
        raise GoogleOAuthError(code, f"Google returned status {response.status_code}")
    try:
        parsed = response.json()
    except ValueError as exc:
        raise GoogleOAuthError("BAD_RESPONSE", "Google returned non-JSON") from exc
    body: dict[str, object] = parsed if isinstance(parsed, dict) else {}

    access = body.get("access_token")
    if not isinstance(access, str) or not access:
        raise GoogleOAuthError(code, "response carried no access token")

    id_token = body.get("id_token")
    refresh = body.get("refresh_token")
    expires_in = body.get("expires_in")
    return OAuthTokens(
        access_token=access,
        id_token=id_token if isinstance(id_token, str) else None,
        refresh_token=refresh if isinstance(refresh, str) else None,
        # Google's access token is opaque, so this duration is the only expiry
        # signal there is.
        expires_in=expires_in
        if isinstance(expires_in, int) and not isinstance(expires_in, bool)
        else None,
    )


async def list_projects(
    client: httpx.AsyncClient,
    *,
    access_token: str,
    endpoint: str = PROJECTS_ENDPOINT,
) -> list[GoogleProject]:
    """List the active GCP projects the signed-in user can see.

    A Google account maps to zero or many projects and the token says nothing
    about which one to bill, so the endpoint Vertex is reached at cannot be
    derived — it has to be chosen. This turns that choice from a free-text box
    into a list.

    Returns ``[]`` rather than raising when the API is disabled or the user
    lacks ``resourcemanager.projects.get``: a sign-in that already succeeded
    must not fail because its project list could not be read. The caller falls
    back to asking for the id directly.
    """
    # httpx is a type-only import in this module; the error class is needed at
    # runtime only on this path.
    import httpx as _httpx

    projects: list[GoogleProject] = []
    page_token: str | None = None

    for _ in range(_MAX_PROJECT_PAGES):
        params = {"filter": "lifecycleState:ACTIVE"}
        if page_token:
            params["pageToken"] = page_token
        try:
            response = await client.get(
                endpoint,
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except _httpx.HTTPError:
            return projects
        if response.status_code >= 400:
            return projects
        try:
            body = response.json()
        except ValueError:
            return projects
        if not isinstance(body, dict):
            return projects

        for raw in body.get("projects") or []:
            if not isinstance(raw, dict):
                continue
            project_id = raw.get("projectId")
            if not isinstance(project_id, str) or not project_id:
                continue
            name = raw.get("name")
            projects.append(
                GoogleProject(
                    project_id=project_id,
                    name=name if isinstance(name, str) and name else project_id,
                )
            )

        next_token = body.get("nextPageToken")
        if not isinstance(next_token, str) or not next_token:
            break
        page_token = next_token

    return projects
