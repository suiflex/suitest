"""`python -m suitest_api` entrypoint — runs uvicorn directly."""

import uvicorn

from suitest_api.settings import get_settings


def main() -> None:
    """Boot uvicorn with the FastAPI app.

    Uses uvicorn's factory mode (``factory=True``) so ``create_app`` is called
    inside the worker after fork — keeps the module import side-effect free
    (no OTel / Prometheus registration at import time). See
    :mod:`suitest_api.main` docstring for the rationale.
    """
    settings = get_settings()
    uvicorn.run(
        "suitest_api.main:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
