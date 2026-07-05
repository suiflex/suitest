"""Local mode skips the credential gate; server mode still requires keys."""

from __future__ import annotations

import os
from unittest import mock

from suitest_lifecycle.mcp_server import verify_credentials


def test_local_mode_skips_credential_check() -> None:
    with mock.patch.dict(os.environ, {"SUITEST_MODE": "local"}, clear=True):
        assert verify_credentials() is None


def test_server_mode_still_requires_keys() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        error = verify_credentials()
        assert error is not None
        assert "SUITEST_API_URL" in error
