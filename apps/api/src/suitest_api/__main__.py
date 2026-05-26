"""`python -m suitest_api` entrypoint — runs uvicorn directly."""

import uvicorn

from suitest_api.settings import get_settings


def main() -> None:
    """Boot uvicorn with the FastAPI app."""
    settings = get_settings()
    uvicorn.run(
        "suitest_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
