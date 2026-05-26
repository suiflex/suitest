"""create_app factory tests."""

import pytest
from asgi_lifespan import LifespanManager
from suitest_api.main import create_app
from suitest_api.settings import Settings


@pytest.mark.asyncio
async def test_create_app_honors_injected_settings() -> None:
    """Custom Settings passed to create_app must survive lifespan startup."""
    custom = Settings(api_port=9999, log_level="DEBUG")
    app = create_app(settings=custom)
    async with LifespanManager(app):
        assert app.state.settings is custom
        assert app.state.settings.api_port == 9999
