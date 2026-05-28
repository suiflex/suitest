"""Inbox read endpoint — aggregated workspace notifications (M1b stub).

The Inbox screen (M1b) lists cards for gating failures, manual-run fails, MCP
health blips, flaky promotions, and agent generation/diagnosis events. M1a
ships only the wire shape so the screen stops 404-ing in real dev; the full
event aggregator lands with the runner + agent in M1d.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from suitest_api.deps.scope import TenantContext, require_workspace_membership

router = APIRouter(prefix="/api/v1", tags=["inbox"])


InboxKind = Literal[
    "DEPLOY_GATE_FAIL",
    "MANUAL_RUN_FAIL",
    "MCP_HEALTH",
    "FLAKY_PROMOTION",
    "AGENT_GENERATION",
    "AGENT_DIAGNOSIS",
]


class InboxItem(BaseModel):
    """One notification card in the Inbox feed."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: InboxKind
    title: str
    body: str
    created_at: str = Field(alias="createdAt")
    status: Literal["unread", "read", "dismissed"] = "unread"


class InboxResponse(BaseModel):
    """``GET /inbox`` envelope — items list + unread badge counter."""

    model_config = ConfigDict(populate_by_name=True)

    items: list[InboxItem] = Field(default_factory=list)
    unread_count: int = Field(default=0, alias="unreadCount")


@router.get("/inbox", response_model=InboxResponse)
async def list_inbox(
    ctx: TenantContext = Depends(require_workspace_membership),
    status_filter: str = Query(default="all", alias="status"),
) -> InboxResponse:
    """List inbox items for the active workspace (empty stub in M1a)."""
    _ = ctx, status_filter
    return InboxResponse(items=[], unread_count=0)
