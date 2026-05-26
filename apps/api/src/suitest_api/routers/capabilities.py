"""/capabilities — public, no auth required."""

from fastapi import APIRouter
from suitest_core.capabilities import CapabilitySnapshot, resolve_capabilities

router = APIRouter(tags=["meta"])


@router.get("/capabilities", response_model=CapabilitySnapshot)
async def get_capabilities() -> CapabilitySnapshot:
    """Return the resolved capability snapshot. Resolves env fresh on each call.

    M0: env-only resolution. M3 will overlay workspace LLMConfig.
    """
    return resolve_capabilities()
