"""Tests for Resend mailer integration in password reset and invitations."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response
from suitest_api.auth.manager import UserManager
from suitest_api.services.mailer_service import MailerService, send_password_reset_email
from suitest_api.settings import Settings
from suitest_db.models.user import User


@pytest.mark.asyncio
async def test_mailer_service_disabled_when_no_api_key() -> None:
    settings = Settings(resend_api_key="", mail_from="sui@keton.id")
    mailer = MailerService(settings=settings)
    assert mailer.is_configured() is False

    # Should be a no-op returning False
    success = await mailer.send_email(
        to="user@example.com",
        subject="Test",
        html="<p>Test</p>",
    )
    assert success is False


@pytest.mark.asyncio
@respx.mock
async def test_mailer_service_sends_email_successfully() -> None:
    settings = Settings(
        resend_api_key="re_test_key_123",
        mail_from="Suitest <sui@keton.id>",
    )
    mailer = MailerService(settings=settings)
    assert mailer.is_configured() is True

    route = respx.post("https://api.resend.com/emails").mock(
        return_value=Response(200, json={"id": "msg_12345"})
    )

    success = await mailer.send_email(
        to="user@example.com",
        subject="Reset Password",
        html="<p>Reset link</p>",
    )

    assert success is True
    assert route.called
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer re_test_key_123"
    import json

    data = json.loads(req.content.decode())
    assert data["from"] == "Suitest <sui@keton.id>"
    assert data["to"] == ["user@example.com"]
    assert data["subject"] == "Reset Password"
    assert data["html"] == "<p>Reset link</p>"


@pytest.mark.asyncio
@respx.mock
async def test_send_password_reset_email_helper() -> None:
    settings = Settings(
        resend_api_key="re_test_key_123",
        mail_from="sui@keton.id",
        web_url="https://sui.keton.id",
    )
    mailer = MailerService(settings=settings)

    route = respx.post("https://api.resend.com/emails").mock(
        return_value=Response(200, json={"id": "msg_999"})
    )

    sent = await send_password_reset_email(
        to_email="rejaisme@gmail.com",
        reset_url="https://sui.keton.id/reset-password?token=sample_token_xyz",
        mailer=mailer,
    )
    assert sent is True
    assert route.called
    import json

    data = json.loads(route.calls.last.request.content.decode())
    assert "https://sui.keton.id/reset-password?token=sample_token_xyz" in data["html"]
    assert "rejaisme@gmail.com" in data["to"]


@pytest.mark.asyncio
async def test_user_manager_on_after_forgot_password_calls_send_email() -> None:
    user = User(
        id=uuid.uuid4(),
        email="target@example.com",
        hashed_password="hash",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )

    mock_session = AsyncMock()
    mock_db = AsyncMock()
    mock_db.session = mock_session

    manager = UserManager(mock_db)

    with (
        patch("suitest_api.auth.manager.PasswordResetRequestRepository") as mock_repo_cls,
        patch(
            "suitest_api.auth.manager.send_password_reset_email", new_callable=AsyncMock
        ) as mock_send,
    ):
        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        await manager.on_after_forgot_password(user, "test-token-abc")

        assert mock_repo.create.called
        assert mock_send.called
        assert mock_send.call_args.kwargs["to_email"] == "target@example.com"
        assert "token=test-token-abc" in mock_send.call_args.kwargs["reset_url"]
