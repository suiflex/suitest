"""MCP startup requires valid Suitest credentials; LLM readiness is not required."""

from __future__ import annotations

import os
from unittest import mock

from suitest_lifecycle.mcp_server import verify_credentials


def test_credentials_are_required() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        error = verify_credentials()
        assert error is not None
        assert "SUITEST_API_URL" in error


def test_valid_credentials_allow_mcp() -> None:
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = b'{"workspaceId":"ws-1"}'
    with (
        mock.patch.dict(
            os.environ,
            {"SUITEST_API_URL": "http://suitest", "SUITEST_API_KEY": "sk_suitest_test"},
            clear=True,
        ),
        mock.patch("urllib.request.urlopen", return_value=response),
    ):
        assert verify_credentials() is None
