"""Transactional email service using Resend REST API."""

from __future__ import annotations

import httpx
import structlog

from suitest_api.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class MailerService:
    """Async transactional email sender backed by Resend."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def is_configured(self) -> bool:
        """Return True if a Resend API key is provided."""
        return bool(self.settings.resend_api_key and self.settings.resend_api_key.strip())

    async def send_email(
        self,
        *,
        to: str | list[str],
        subject: str,
        html: str,
        text: str | None = None,
    ) -> bool:
        """Send an email via Resend. Return True on success, False on failure or not configured."""
        if not self.is_configured():
            logger.debug("resend mailer is not configured, skipping send", to=to, subject=subject)
            return False

        recipients = [to] if isinstance(to, str) else to
        payload: dict[str, object] = {
            "from": self.settings.mail_from,
            "to": recipients,
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text

        headers = {
            "Authorization": f"Bearer {self.settings.resend_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(RESEND_API_URL, json=payload, headers=headers)
                if response.is_success:
                    data = response.json()
                    logger.info(
                        "email sent via resend",
                        to=recipients,
                        subject=subject,
                        message_id=data.get("id"),
                    )
                    return True
                logger.error(
                    "resend api returned error",
                    status_code=response.status_code,
                    body=response.text,
                    to=recipients,
                )
                return False
        except Exception as exc:
            logger.error("failed sending email via resend", error=str(exc), to=recipients)
            return False


async def send_password_reset_email(
    *,
    to_email: str,
    reset_url: str,
    mailer: MailerService | None = None,
) -> bool:
    """Send formatted password reset email to user."""
    service = mailer or MailerService()
    if not service.is_configured():
        return False

    subject = "Reset your password for Suitest"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Reset your password</title>
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0a0a0a; color: #fafafa; padding: 24px; }}
        .card {{ max-width: 500px; margin: 0 auto; background-color: #111111; border: 1px solid #262626; border-radius: 8px; padding: 32px; }}
        h2 {{ color: #fafafa; margin-top: 0; }}
        p {{ color: #a3a3a3; line-height: 1.5; font-size: 15px; }}
        .button {{ display: inline-block; background-color: #4ade80; color: #000000; text-decoration: none; font-weight: 600; padding: 12px 24px; border-radius: 6px; margin: 20px 0; }}
        .muted {{ font-size: 13px; color: #737373; word-break: break-all; }}
      </style>
    </head>
    <body>
      <div class="card">
        <h2>Reset your password</h2>
        <p>We received a request to reset your password for your Suitest account. Click the button below to choose a new password:</p>
        <p><a href="{reset_url}" class="button">Reset Password</a></p>
        <p class="muted">Or copy and paste this link into your browser:<br>{reset_url}</p>
        <p class="muted">This link will expire in 1 hour. If you didn't request this, you can safely ignore this email.</p>
      </div>
    </body>
    </html>
    """
    text = (
        f"Reset your password for Suitest\n\n"
        f"Click the link below to set a new password:\n{reset_url}\n\n"
        f"This link expires in 1 hour. If you did not request this, please ignore this email."
    )
    return await service.send_email(to=to_email, subject=subject, html=html, text=text)
