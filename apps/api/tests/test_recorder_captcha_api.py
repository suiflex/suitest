"""Integration tests for live recorder CAPTCHA solve endpoint."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from suitest_api.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_solve_captcha_endpoint_with_base64_canvas(app) -> None:
    dummy_b64 = base64.b64encode(b"fake_png_data").decode("ascii")
    payload = {
        "image_base64": f"data:image/png;base64,{dummy_b64}",
        "image_selector": "#img-captcha",
        "input_selector": "#captcha",
        "captcha_type": "auto",
        "force_uppercase": True,
    }

    mock_session = MagicMock(id="test_session", workspace_id="ws_test")

    with (
        patch(
            "suitest_db.repositories.recorder_sessions.RecorderSessionRepo.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_session,
        ),
        patch(
            "suitest_db.repositories.llm_configs.LLMConfigRepo.get_active",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "suitest_agent.generators.captcha_solver.solve_captcha_image",
            new_callable=AsyncMock,
        ) as mock_solver,
    ):
        mock_solver.return_value = "PRINGSEWU"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/generators/recorder/sessions/test_session/solve-captcha",
                json=payload,
            )
            assert res.status_code == 200, res.text
            data = res.json()
            assert data["status"] == "success"
            assert data["text"] == "PRINGSEWU"
            assert data["source"] == "client_canvas"
            mock_solver.assert_called_once()
            call_kwargs = mock_solver.call_args.kwargs
            assert call_kwargs["force_uppercase"] is True
            assert call_kwargs["captcha_type"] == "auto"


@pytest.mark.asyncio
async def test_solve_captcha_endpoint_playwright_snapshot_fallback(app) -> None:
    payload = {
        "image_base64": None,
        "image_selector": "#img-captcha",
        "input_selector": "#captcha",
        "captcha_type": "math",
        "force_uppercase": False,
    }

    mock_session = MagicMock(id="test_session", workspace_id="ws_test")
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_locator.wait_for = AsyncMock()
    mock_locator.evaluate = AsyncMock()
    mock_locator.screenshot = AsyncMock(return_value=b"playwright_png_bytes")
    mock_page.locator.return_value.first = mock_locator

    with (
        patch(
            "suitest_db.repositories.recorder_sessions.RecorderSessionRepo.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_session,
        ),
        patch(
            "suitest_db.repositories.llm_configs.LLMConfigRepo.get_active",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "suitest_agent.generators.browser_launcher.get_headed_session_page",
            return_value=mock_page,
        ),
        patch(
            "suitest_agent.generators.captcha_solver.solve_captcha_image",
            new_callable=AsyncMock,
        ) as mock_solver,
    ):
        mock_solver.return_value = "12"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/generators/recorder/sessions/test_session/solve-captcha",
                json=payload,
            )
            assert res.status_code == 200, res.text
            data = res.json()
            assert data["status"] == "success"
            assert data["text"] == "12"
            assert data["source"] == "playwright_snapshot"
            mock_solver.assert_called_once()
            call_kwargs = mock_solver.call_args.kwargs
            assert call_kwargs["captcha_type"] == "math"


@pytest.mark.asyncio
async def test_solve_captcha_endpoint_cors_options(app) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.options(
            "/api/v1/generators/recorder/sessions/test_session/solve-captcha",
            headers={"Origin": "https://app.example.com"},
        )
        assert res.status_code == 204
        assert res.headers.get("access-control-allow-origin") == "https://app.example.com"
