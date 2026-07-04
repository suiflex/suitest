"""Slack notifier adapter — POSTs Block Kit messages to an incoming webhook URL.

Slack is wired as a :class:`NotifierAdapter` (not :class:`IssueTrackerAdapter`)
because incoming webhooks have neither issue-id nor status-transition
semantics — a single POST drops a Block Kit payload on the channel the
webhook was minted for and that's it.

Wire details (per Slack's `chat.postMessage` Block Kit reference):

* Webhook URL stored AES-GCM-encrypted in
  ``integrations.secrets_encrypted`` as a JSON string with one key,
  ``{"webhook_url": "https://hooks.slack.com/services/T.../B.../..."}``.
* :meth:`SlackAdapter.test_connection` posts a "Suitest connection test"
  message (Q9 — intrusive but the FE confirms via dialog before invoking).
* :meth:`SlackAdapter.send_notification` builds the canonical defect Block
  Kit payload: header with severity emoji + defect public id, section with
  title / category / severity / back-link, color attachment driven by
  ``Severity`` (LOW / MEDIUM / HIGH / CRITICAL → ``#9CA3AF`` /
  ``#FBBF24`` / ``#F87171`` / ``#DC2626``).

Errors are translated to :class:`AdapterError` subclasses so the ARQ job's
``except AdapterError`` retry decision stays one type:

* HTTP timeout → :class:`AdapterTimeoutError` (ARQ retries with backoff).
* Non-200 from Slack → :class:`AdapterRemoteError` (ARQ retries; terminal
  fail flips ``integration.status=error``).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import httpx
from suitest_core.crypto import decrypt as crypto_decrypt
from suitest_shared.domain.enums import DiagnosisKind, IntegrationKind, Severity

from suitest_api.integrations.base import (
    AdapterRemoteError,
    AdapterTimeoutError,
    ConnectionTestResult,
    DefectEvent,
    NotificationResult,
)

if TYPE_CHECKING:
    from suitest_db.models.integration import Integration


# Severity → Slack attachment color hex. Slack renders the bar on the left of the attachment in this color, which is
# the only severity-visualisation channel Block Kit gives us without dropping
# down to `chat.postMessage` proper (webhooks don't support reactions /
# threads). Hex values are intentionally NOT pulled from `tailwind.config.ts`
# because Slack expects a static 6-digit RGB string, not a Tailwind token.
SEVERITY_COLOR: Final[dict[Severity, str]] = {
    Severity.LOW: "#9CA3AF",
    Severity.MEDIUM: "#FBBF24",
    Severity.HIGH: "#F87171",
    Severity.CRITICAL: "#DC2626",
}

# Severity → header emoji. Kept in lock-step with SEVERITY_COLOR so the
# rendered Slack message tells the same story across both visual channels.
SEVERITY_EMOJI: Final[dict[Severity, str]] = {
    Severity.LOW: ":information_source:",
    Severity.MEDIUM: ":warning:",
    Severity.HIGH: ":rotating_light:",
    Severity.CRITICAL: ":fire:",
}

# Diagnosis label → human-readable string for the Slack section block. Slack
# users don't speak `MANUAL_TRIAGE` — surface `Triage` etc. The
# canonical enum source is `docs/DATA_MODEL.md §6`.
DIAGNOSIS_LABEL: Final[dict[DiagnosisKind, str]] = {
    DiagnosisKind.REGRESSION: "Regression",
    DiagnosisKind.FLAKE: "Flaky",
    DiagnosisKind.INFRA: "Infrastructure",
    DiagnosisKind.SPEC_DRIFT: "Spec drift",
    DiagnosisKind.MANUAL_TRIAGE: "Manual triage",
}


# Per-request HTTP timeout for the Slack webhook POST. Slack's published SLA
# is "< 5s p99"; 10s is a safety margin that keeps the ARQ retry budget from
# burning a single attempt on a slow round-trip.
DEFAULT_WEBHOOK_TIMEOUT_SECONDS: Final[float] = 10.0


class SlackAdapter:
    """Notifier adapter that POSTs Block Kit payloads to a Slack incoming webhook.

    Constructed once per :class:`Integration` row inside the ARQ job (so each
    workspace's distinct webhook URL is decrypted lazily, never at module
    import time). The :class:`httpx.AsyncClient` is injected so tests can
    swap in a ``respx`` mock transport.

    The ``crypto_decrypt`` callable is also injected so a unit test can avoid
    threading a real ``SUITEST_ENCRYPTION_KEY`` through every call — the
    production wiring passes :func:`suitest_core.crypto.decrypt` directly.
    """

    kind: IntegrationKind = IntegrationKind.SLACK

    def __init__(
        self,
        integration: Integration,
        http_client: httpx.AsyncClient,
        decrypt: Any = crypto_decrypt,
    ) -> None:
        self.integration = integration
        self._http = http_client
        # Injected for testability; real callers pass the module-level
        # ``decrypt`` from :mod:`suitest_core.crypto` which reads the env key.
        self._decrypt = decrypt

    # ------------------------------------------------------------------
    # Public surface (NotifierAdapter Protocol)
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectionTestResult:
        """POST a "Suitest connection test" message to the configured webhook.

        Returns :class:`ConnectionTestResult` with ``ok=True`` on a 200
        response; on any failure (timeout / non-200 / bad JSON in secrets)
        returns ``ok=False`` with the human-readable error string so the FE
        renders it inline rather than 500-ing the request.
        """
        try:
            webhook_url = self._resolve_webhook_url()
        except (AdapterRemoteError, ValueError) as exc:
            return ConnectionTestResult(ok=False, error=str(exc))

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Suitest connection test* — this message confirms the "
                        "incoming webhook is reachable. You can disconnect this "
                        "integration any time from Settings → Integrations."
                    ),
                },
            }
        ]
        try:
            await self._post_blocks(webhook_url, blocks=blocks, color=None)
        except AdapterTimeoutError as exc:
            return ConnectionTestResult(ok=False, error=f"Slack timeout: {exc}")
        except AdapterRemoteError as exc:
            return ConnectionTestResult(ok=False, error=f"Slack rejected webhook: {exc}")
        return ConnectionTestResult(ok=True, display_name="Slack Incoming Webhook")

    async def send_notification(
        self,
        event: DefectEvent,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> NotificationResult:
        """Render ``event`` as Block Kit blocks and POST to the webhook.

        ``config`` may carry per-integration overrides for the Suitest base URL
        the back-link points at (``config["suitest_base_url"]``); the event
        carries a fallback. ``secrets`` is the already-decrypted dict — the
        caller (ARQ job) does the AES-GCM decrypt once and hands the plaintext
        dict to the adapter so the adapter doesn't hold a key.
        """
        webhook_url = secrets.get("webhook_url")
        if not isinstance(webhook_url, str) or not webhook_url:
            raise AdapterRemoteError(
                "Slack integration secrets missing required 'webhook_url' field"
            )

        base_url = config.get("suitest_base_url") or event.suitest_base_url
        blocks = build_defect_blocks(event, suitest_base_url=base_url)
        color = SEVERITY_COLOR[event.severity]
        await self._post_blocks(webhook_url, blocks=blocks, color=color)
        # Slack incoming webhooks return literal ``"ok"`` as body with no
        # message id, so we surface ``sent=True`` and leave ``message_id``
        # at its default ``None``.
        return NotificationResult(sent=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_webhook_url(self) -> str:
        """Decrypt + parse ``integration.secrets_encrypted`` → webhook URL.

        Raises :class:`AdapterRemoteError` on malformed secrets (missing blob,
        bad JSON, missing key) so the caller can translate to the user-facing
        error envelope without leaking crypto detail. Decryption errors are
        intentionally re-raised as :class:`AdapterRemoteError` because the
        operator's only fix is to re-save the integration with a fresh webhook.
        """
        raw = self.integration.secrets_encrypted
        if not raw:
            raise AdapterRemoteError("Slack integration is missing its webhook URL secret")
        try:
            # ``secrets_encrypted`` is exposed as ``str`` via the
            # ``EncryptedBytes`` SQLAlchemy type, which transparently decrypts
            # on load. The stored shape is a JSON object — we deserialise here
            # rather than at adapter construction time so a malformed row only
            # surfaces when a notification fires (not at startup).
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterRemoteError("Slack integration secrets are not valid JSON") from exc
        if not isinstance(payload, dict):
            raise AdapterRemoteError(
                "Slack integration secrets must be a JSON object with 'webhook_url'"
            )
        webhook_url = payload.get("webhook_url")
        if not isinstance(webhook_url, str) or not webhook_url:
            raise AdapterRemoteError(
                "Slack integration secrets missing required 'webhook_url' field"
            )
        return webhook_url

    async def _post_blocks(
        self,
        webhook_url: str,
        *,
        blocks: list[dict[str, Any]],
        color: str | None,
    ) -> None:
        """POST ``blocks`` to the webhook, translating httpx errors to AdapterError.

        Slack accepts the Block Kit payload either at the top level
        (``{"blocks": [...]}``) or wrapped in an attachment when a color bar
        is desired (``{"attachments": [{"color": "#...", "blocks": [...]}]}``).
        We use the attachment form whenever ``color`` is set because incoming
        webhooks have no other channel for severity color, and the top-level
        form when posting a plain confirmation message (test_connection).
        """
        body: dict[str, Any]
        if color is None:
            body = {"blocks": blocks}
        else:
            body = {"attachments": [{"color": color, "blocks": blocks}]}
        try:
            response = await self._http.post(
                webhook_url,
                json=body,
                timeout=DEFAULT_WEBHOOK_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(
                f"Slack webhook POST timed out after {DEFAULT_WEBHOOK_TIMEOUT_SECONDS}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise AdapterRemoteError(f"Slack webhook POST failed: {exc}") from exc

        if response.status_code != 200:
            # Slack returns plain-text body for webhook errors (``invalid_token``,
            # ``channel_not_found``, etc.). Surface the body so the ARQ job's
            # ``integration.error`` WS event tells the operator exactly why.
            raise AdapterRemoteError(
                f"Slack webhook rejected payload: HTTP {response.status_code} {response.text!r}"
            )


def build_defect_blocks(
    event: DefectEvent,
    *,
    suitest_base_url: str | None,
) -> list[dict[str, Any]]:
    """Pure helper: build the Block Kit payload for ``event``.

    Pulled out of :class:`SlackAdapter` so unit tests can assert the JSON
    shape without a real HTTP client. Three blocks:

    1. Header — severity emoji + ``[DEF-42] title``.
    2. Section — diagnosis kind, severity, and the back-link to the Suitest
       run (when both ``suitest_base_url`` and ``event.run_id`` are present).
    3. Context — test case public id (when available).

    The block list deliberately stays small (≤ 3 blocks) so the message
    renders cleanly in mobile Slack and respects the implicit Block Kit
    character budgets.
    """
    severity = event.severity
    diagnosis_label = DIAGNOSIS_LABEL.get(event.diagnosis_kind, event.diagnosis_kind.value)
    emoji = SEVERITY_EMOJI[severity]

    header_text = f"{emoji} [{event.defect_public_id}] {event.title}"
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text[:150],  # Block Kit header cap
                "emoji": True,
            },
        }
    ]

    section_fields: list[dict[str, str]] = [
        {"type": "mrkdwn", "text": f"*Severity*\n{severity.value}"},
        {"type": "mrkdwn", "text": f"*Diagnosis*\n{diagnosis_label}"},
    ]
    if event.test_case_public_id is not None:
        section_fields.append(
            {"type": "mrkdwn", "text": f"*Test case*\n{event.test_case_public_id}"}
        )
    if event.run_id is not None and suitest_base_url:
        run_url = f"{suitest_base_url.rstrip('/')}/runs/{event.run_id}"
        section_fields.append({"type": "mrkdwn", "text": f"*Run*\n<{run_url}|Open in Suitest>"})

    blocks.append({"type": "section", "fields": section_fields})

    if suitest_base_url:
        defect_url = f"{suitest_base_url.rstrip('/')}/defects/{event.defect_public_id}"
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"<{defect_url}|View defect {event.defect_public_id}>",
                    }
                ],
            }
        )

    return blocks
