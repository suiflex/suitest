"""Spend alert service — M7-4 Slack/email notifications when spend crosses caps.

Alerts fire when workspace or per-user spend crosses 80% or 100% of the
configured cap.  Alert destinations are read from the active workspace
``LLMConfig.config_json``:

* ``slack_webhook_url`` (str | None) — Slack Incoming Webhook URL.
* ``alert_email`` (str | None) — recipient email (logged as a structured
  warning; real SMTP delivery is a M4+ concern).

Idempotency: a simple in-memory TTL cache tracks the last alert percentage
per ``(workspace_id, user_id | None)`` key, so a burst of LLM calls does not
produce duplicate notifications within the same hour.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from suitest_db.repositories.llm_configs import LLMConfigRepo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

# Alert thresholds (fractions of the cap).
_THRESHOLDS: tuple[float, ...] = (0.8, 1.0)

# In-memory cache: key → (last_alert_pct, timestamp)
# Expires after _ALERT_TTL_SECONDS so alerts can fire again once the window resets.
_ALERT_TTL_SECONDS = 3600  # 1 hour
_alert_cache: dict[str, tuple[float, float]] = {}


def _cache_key(workspace_id: str, user_id: str | None) -> str:
    return f"{workspace_id}:{user_id or '__workspace__'}"


def _already_alerted(key: str, pct: float) -> bool:
    """Return ``True`` if we already sent an alert at or above ``pct`` recently."""
    entry = _alert_cache.get(key)
    if entry is None:
        return False
    last_pct, ts = entry
    if time.monotonic() - ts > _ALERT_TTL_SECONDS:
        # Cache entry expired — clear it.
        del _alert_cache[key]
        return False
    return last_pct >= pct


def _record_alert(key: str, pct: float) -> None:
    _alert_cache[key] = (pct, time.monotonic())


class SpendAlertService:
    """Evaluate spend thresholds and dispatch webhook/log alerts."""

    async def maybe_alert(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str | None,
        *,
        cap_usd: float,
        current_usd: float,
        label: str = "workspace",
    ) -> None:
        """Send webhook/log alert if spend just crossed 80% or 100% of ``cap_usd``.

        Args:
            session: Async session (for reading LLMConfig).
            workspace_id: Workspace scoping for config lookup + cache key.
            user_id: The user whose budget is being evaluated, or ``None`` for
                workspace-level checks.
            cap_usd: The configured cap.  Pass ``0`` to skip the alert entirely.
            current_usd: Current accumulated spend.
            label: Human-readable label for the alert message (e.g. ``"daily"``,
                ``"monthly"``, ``"workspace daily"``).
        """
        if cap_usd <= 0:
            return

        pct = current_usd / cap_usd
        key = _cache_key(workspace_id, user_id)

        # Find the highest threshold crossed.
        fired_threshold: float | None = None
        for threshold in sorted(_THRESHOLDS, reverse=True):
            if pct >= threshold and not _already_alerted(key, threshold):
                fired_threshold = threshold
                break

        if fired_threshold is None:
            return

        _record_alert(key, fired_threshold)
        pct_label = f"{fired_threshold * 100:.0f}%"
        msg = (
            f"[Suitest] {label} spend alert: "
            f"${current_usd:.2f} / ${cap_usd:.2f} ({pct_label}) "
            f"for workspace={workspace_id}" + (f", user={user_id}" if user_id else "")
        )

        config = await LLMConfigRepo(session).get_active(workspace_id)
        slack_url: str | None = None
        alert_email: str | None = None
        if config is not None:
            raw_slack = config.config_json.get("slack_webhook_url")
            if isinstance(raw_slack, str) and raw_slack:
                slack_url = raw_slack
            raw_email = config.config_json.get("alert_email")
            if isinstance(raw_email, str) and raw_email:
                alert_email = raw_email

        if slack_url:
            await self._post_slack(slack_url, msg)

        if alert_email:
            _log.warning(
                "spend_alert email (not yet delivered via SMTP, M4+): to=%s msg=%s",
                alert_email,
                msg,
            )
        else:
            _log.warning("spend_alert: %s", msg)

    async def _post_slack(self, webhook_url: str, text: str) -> None:
        """POST a Slack Incoming Webhook.  Errors are logged and swallowed."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(webhook_url, json={"text": text})
                if resp.status_code != 200:
                    _log.warning(
                        "spend_alert: Slack webhook returned %s: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
        except Exception as exc:
            _log.warning("spend_alert: Slack webhook failed: %s", exc)
