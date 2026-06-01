"""MCP provider registry CRUD — Integrations → MCP Servers (docs/MCP_PLUGINS.md §5).

Workspace-scoped registry of MCP servers. The list/detail read paths surface the
bundled builtins (``api-http-mcp`` / ``playwright-mcp`` / ``postgres-mcp`` + the
M2-10 additions) on top of any custom rows the workspace registered. Secrets are
**never** decrypted onto a response — the model's ``secrets_json_encrypted``
column stays server-side; reads expose names + transport + health + the
discovered tool catalog only.

Milestone history:
* M1b shipped read-only ``GET /mcp/providers``.
* M2-6 adds the full CRUD surface (``POST`` / ``GET :id`` / ``PATCH`` / ``DELETE``).
* M2-7 layers connect → handshake → ``tools/list`` validation on register.
* M2-8 adds ``/discover`` + ``/invoke`` (the tool browser).

Bundled builtins are read-only: they carry a synthetic ``builtin:<name>`` id and
cannot be edited or deleted (a workspace overrides one by registering a custom
row with the same ``name`` — see :mod:`suitest_mcp.registry`).
"""

from __future__ import annotations

import json
import shlex
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.mcp_providers import (
    McpProviderCreate,
    McpProviderRepo,
    McpProviderUpdate,
)
from suitest_mcp.discovery import DiscoveryResult, McpDiscoveryError, discover_provider
from suitest_mcp.models import McpProviderConfig as ProbeConfig
from suitest_mcp.models import McpTransport as ProbeTransport
from suitest_mcp.providers.builtin_specs import BUILTIN_SPECS
from suitest_shared.domain.enums import McpTransport, Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership

router = APIRouter(prefix="/api/v1", tags=["mcp"])

_WRITE_ROLES = {Role.QA, Role.ADMIN, Role.OWNER}
_BUILTIN_PREFIX = "builtin:"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class McpProviderTool(BaseModel):
    """One tool entry (name + description + flattened arg schema preview)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str = ""
    arg_schema: dict[str, Any] | None = Field(default=None, alias="argSchema")


class McpProviderPublic(BaseModel):
    """Summary row — name + transport + health + tool names (no secrets)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    kind: str
    transport: str
    endpoint: str
    health_status: str = Field(default="unknown", alias="healthStatus")
    last_health_at: datetime | None = Field(default=None, alias="lastHealthAt")
    is_bundled: bool = Field(default=False, alias="isBundled")
    enabled: bool = True
    is_default_for_target: dict[str, bool] = Field(default_factory=dict, alias="isDefaultForTarget")
    tools: list[McpProviderTool] = Field(default_factory=list)


class McpProviderDetail(McpProviderPublic):
    """Detail row — summary + config preview (secrets redacted) + version pins."""

    model_config = ConfigDict(populate_by_name=True)

    config_json: dict[str, Any] = Field(default_factory=dict, alias="configJson")
    has_secrets: bool = Field(default=False, alias="hasSecrets")
    command_pin: str | None = Field(default=None, alias="commandPin")
    image_pin: str | None = Field(default=None, alias="imagePin")
    version_pin: str | None = Field(default=None, alias="versionPin")
    git_ref: str | None = Field(default=None, alias="gitRef")


class McpProvidersResponse(BaseModel):
    """``GET /mcp/providers`` envelope (bundled builtins + custom rows)."""

    items: list[McpProviderPublic] = Field(default_factory=list)


class McpProviderCreateBody(BaseModel):
    """``POST /mcp/providers`` body — register a custom MCP server."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=64)
    endpoint: str = Field(min_length=1, max_length=1024)
    transport: McpTransport
    config_json: dict[str, Any] | None = Field(default=None, alias="configJson")
    secrets_json: dict[str, Any] | str | None = Field(default=None, alias="secretsJson")
    is_default_for_target: dict[str, bool] | None = Field(default=None, alias="isDefaultForTarget")
    # When True (default) the server connects, handshakes, and runs tools/list
    # before persisting (M2-7). Set False to register without a live probe
    # (e.g. seeding, or a provider not reachable yet).
    validate_on_register: bool = Field(default=True, alias="validate")


class McpProviderProbeResult(BaseModel):
    """``POST /mcp/providers/test-connection`` response — dry-run discovery."""

    model_config = ConfigDict(populate_by_name=True)

    ok: bool
    tools: list[McpProviderTool] = Field(default_factory=list)
    server_version: str | None = Field(default=None, alias="serverVersion")


class McpProviderUpdateBody(BaseModel):
    """``PATCH /mcp/providers/:id`` body — partial update of a custom row."""

    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, max_length=120)
    kind: str | None = Field(default=None, max_length=64)
    endpoint: str | None = Field(default=None, max_length=1024)
    transport: McpTransport | None = None
    config_json: dict[str, Any] | None = Field(default=None, alias="configJson")
    secrets_json: dict[str, Any] | str | None = Field(default=None, alias="secretsJson")
    is_default_for_target: dict[str, bool] | None = Field(default=None, alias="isDefaultForTarget")
    enabled: bool | None = None


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def _normalize_tools(config_json: dict[str, Any]) -> list[McpProviderTool]:
    """Coerce ``config_json['tools']`` into a uniform tool list.

    Builtins store a bare ``list[str]`` of tool names; custom providers store
    the discovered ``list[{name, description, input_schema}]`` from ``tools/list``.
    """
    raw = config_json.get("tools", [])
    if not isinstance(raw, list):
        return []
    out: list[McpProviderTool] = []
    for entry in raw:
        if isinstance(entry, str):
            out.append(McpProviderTool(name=entry))
        elif isinstance(entry, dict) and entry.get("name"):
            schema = entry.get("input_schema") or entry.get("argSchema") or {}
            props = schema.get("properties", {}) if isinstance(schema, dict) else {}
            out.append(
                McpProviderTool(
                    name=str(entry["name"]),
                    description=str(entry.get("description", "")),
                    arg_schema=props or None,
                )
            )
    return out


def _builtin_summaries() -> list[McpProviderPublic]:
    """Every bundled builtin as a read-only summary row."""
    return [
        McpProviderPublic(
            id=spec.id,
            name=spec.name,
            kind=spec.kind,
            transport=spec.transport.value,
            endpoint=spec.endpoint,
            health_status="unknown",
            is_bundled=True,
            enabled=True,
            is_default_for_target=dict(spec.is_default_for_target),
            tools=_normalize_tools(spec.config_json),
        )
        for spec in BUILTIN_SPECS
    ]


def _builtin_detail(spec_id: str) -> McpProviderDetail | None:
    for spec in BUILTIN_SPECS:
        if spec.id == spec_id:
            return McpProviderDetail(
                id=spec.id,
                name=spec.name,
                kind=spec.kind,
                transport=spec.transport.value,
                endpoint=spec.endpoint,
                health_status="unknown",
                is_bundled=True,
                enabled=True,
                is_default_for_target=dict(spec.is_default_for_target),
                tools=_normalize_tools(spec.config_json),
                config_json=dict(spec.config_json),
                has_secrets=False,
            )
    return None


def _row_to_summary(row: Any) -> McpProviderPublic:
    transport = row.transport.value if hasattr(row.transport, "value") else str(row.transport)
    return McpProviderPublic(
        id=row.id,
        name=row.name,
        kind=row.kind,
        transport=transport,
        endpoint=row.endpoint,
        health_status=row.health_status,
        last_health_at=row.last_health_at,
        is_bundled=False,
        enabled=row.enabled,
        is_default_for_target=dict(row.is_default_for_target or {}),
        tools=_normalize_tools(row.config_json or {}),
    )


def _row_to_detail(row: Any) -> McpProviderDetail:
    transport = row.transport.value if hasattr(row.transport, "value") else str(row.transport)
    # config preview never includes secrets (those live in secrets_json_encrypted).
    return McpProviderDetail(
        id=row.id,
        name=row.name,
        kind=row.kind,
        transport=transport,
        endpoint=row.endpoint,
        health_status=row.health_status,
        last_health_at=row.last_health_at,
        is_bundled=False,
        enabled=row.enabled,
        is_default_for_target=dict(row.is_default_for_target or {}),
        tools=_normalize_tools(row.config_json or {}),
        config_json=dict(row.config_json or {}),
        has_secrets=row.secrets_json_encrypted is not None,
        command_pin=row.command_pin,
        image_pin=row.image_pin,
        version_pin=row.version_pin,
        git_ref=row.git_ref,
    )


def _serialize_secrets(secrets: dict[str, Any] | str | None) -> str | None:
    if secrets is None:
        return None
    if isinstance(secrets, str):
        return secrets
    return json.dumps(secrets)


def _build_config_json(
    transport: McpTransport, endpoint: str, config_json: dict[str, Any] | None
) -> dict[str, Any]:
    """Merge caller config with derived knobs.

    For stdio providers the ``endpoint`` is a shell command; we parse it into
    ``config_json['command']`` (argv list) when the caller did not supply one,
    so the registry / client can spawn it without re-parsing.
    """
    cfg: dict[str, Any] = dict(config_json or {})
    if transport == McpTransport.STDIO and "command" not in cfg and endpoint:
        cfg["command"] = shlex.split(endpoint)
    return cfg


def _secrets_env(secrets: dict[str, Any] | str | None) -> dict[str, str]:
    """Coerce the write-only secrets payload into string env vars for the probe.

    Secrets are injected as environment variables for the (sub)process / handshake
    context per MCP_PLUGINS §6 — never logged. A JSON string is parsed first.
    """
    if secrets is None:
        return {}
    parsed: dict[str, Any]
    if isinstance(secrets, str):
        try:
            loaded = json.loads(secrets)
        except json.JSONDecodeError:
            return {}
        parsed = loaded if isinstance(loaded, dict) else {}
    else:
        parsed = secrets
    return {str(k): str(v) for k, v in parsed.items()}


def _probe_config(
    *,
    workspace_id: str,
    name: str,
    kind: str,
    endpoint: str,
    transport: McpTransport,
    config_json: dict[str, Any] | None,
    secrets_json: dict[str, Any] | str | None,
) -> ProbeConfig:
    """Build an in-memory provider config for a discovery probe (no DB row)."""
    cfg = _build_config_json(transport, endpoint, config_json)
    env = {str(k): str(v) for k, v in (cfg.get("env") or {}).items()}
    env.update(_secrets_env(secrets_json))
    return ProbeConfig(
        id="probe",
        workspace_id=workspace_id,
        name=name,
        kind=kind,
        transport=ProbeTransport(transport.value),
        endpoint=endpoint,
        command=list(cfg.get("command", [])),
        env=env,
        config_json=cfg,
        spawn_timeout_seconds=float(cfg.get("spawn_timeout_seconds", 15.0)),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/mcp/providers", response_model=McpProvidersResponse)
async def list_mcp_providers(
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> McpProvidersResponse:
    """List MCP providers — bundled builtins (pinned) + custom workspace rows."""
    rows = await McpProviderRepo(session).list_by_workspace(workspace_id=ctx.workspace_id)
    return McpProvidersResponse(items=[*_builtin_summaries(), *(_row_to_summary(r) for r in rows)])


@router.get("/mcp/providers/{provider_id}", response_model=McpProviderDetail)
async def get_mcp_provider(
    provider_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> McpProviderDetail:
    """Provider detail — config preview + discovered tool catalog (no secrets)."""
    if provider_id.startswith(_BUILTIN_PREFIX):
        builtin = _builtin_detail(provider_id)
        if builtin is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="provider not found")
        return builtin
    repo = McpProviderRepo(session)
    row = await repo.get_by_id(provider_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="provider not found")
    return _row_to_detail(row)


@router.post(
    "/mcp/providers",
    response_model=McpProviderDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_mcp_provider(
    body: McpProviderCreateBody,
    ctx: TenantContext = Depends(require_role(_WRITE_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> McpProviderDetail:
    """Register a custom MCP server.

    With ``validate=true`` (default) the server connects, performs the MCP
    ``initialize`` handshake, runs ``tools/list``, and persists the discovered
    catalog + ``health_status=ok`` + version pins (M2-7). A failed probe rejects
    the registration with ``422 MCP_REGISTRATION_FAILED`` and writes no row.
    """
    repo = McpProviderRepo(session)
    if await repo.get_by_name(ctx.workspace_id, body.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"provider {body.name!r} already exists in this workspace",
        )

    config_json = _build_config_json(body.transport, body.endpoint, body.config_json)
    discovery: DiscoveryResult | None = None
    if body.validate_on_register:
        try:
            discovery = await discover_provider(
                _probe_config(
                    workspace_id=ctx.workspace_id,
                    name=body.name,
                    kind=body.kind,
                    endpoint=body.endpoint,
                    transport=body.transport,
                    config_json=body.config_json,
                    secrets_json=body.secrets_json,
                )
            )
        except McpDiscoveryError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "MCP_REGISTRATION_FAILED", "message": str(exc)},
            ) from exc
        config_json["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in discovery.tools
        ]

    row = await repo.create(
        McpProviderCreate(
            workspace_id=ctx.workspace_id,
            name=body.name,
            kind=body.kind,
            endpoint=body.endpoint,
            transport=body.transport,
            config_json=config_json,
            secrets_json_encrypted=_serialize_secrets(body.secrets_json),
            is_default_for_target=body.is_default_for_target or {},
        )
    )
    if discovery is not None:
        row.health_status = "ok"
        if body.transport == McpTransport.STDIO:
            row.command_pin = body.endpoint[:200]
        elif discovery.server_version is not None:
            row.version_pin = discovery.server_version[:100]
        await session.flush()
    await session.commit()
    await session.refresh(row)
    return _row_to_detail(row)


@router.post("/mcp/providers/test-connection", response_model=McpProviderProbeResult)
async def test_mcp_connection(
    body: McpProviderCreateBody,
    ctx: TenantContext = Depends(require_role(_WRITE_ROLES)),
) -> McpProviderProbeResult:
    """Dry-run connect + ``tools/list`` without persisting (M2-7 register modal).

    Lets the UI flip the form's status pill before the user saves. Failures
    surface as ``422 MCP_REGISTRATION_FAILED``.
    """
    try:
        discovery = await discover_provider(
            _probe_config(
                workspace_id=ctx.workspace_id,
                name=body.name,
                kind=body.kind,
                endpoint=body.endpoint,
                transport=body.transport,
                config_json=body.config_json,
                secrets_json=body.secrets_json,
            )
        )
    except McpDiscoveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "MCP_REGISTRATION_FAILED", "message": str(exc)},
        ) from exc
    return McpProviderProbeResult(
        ok=True,
        tools=[
            McpProviderTool(
                name=t.name,
                description=t.description,
                arg_schema=t.input_schema.get("properties") or None,
            )
            for t in discovery.tools
        ],
        server_version=discovery.server_version,
    )


@router.patch("/mcp/providers/{provider_id}", response_model=McpProviderDetail)
async def update_mcp_provider(
    provider_id: str,
    body: McpProviderUpdateBody,
    ctx: TenantContext = Depends(require_role(_WRITE_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> McpProviderDetail:
    """Patch a custom provider. Builtins are read-only (409)."""
    if provider_id.startswith(_BUILTIN_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="bundled providers are read-only"
        )
    repo = McpProviderRepo(session)
    row = await repo.get_by_id(provider_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="provider not found")

    transport = body.transport or row.transport
    config_json = body.config_json
    if config_json is not None or body.endpoint is not None:
        endpoint = body.endpoint if body.endpoint is not None else row.endpoint
        config_json = _build_config_json(transport, endpoint, config_json or dict(row.config_json))

    update = McpProviderUpdate(
        name=body.name,
        kind=body.kind,
        endpoint=body.endpoint,
        transport=body.transport,
        config_json=config_json,
        secrets_json_encrypted=_serialize_secrets(body.secrets_json),
        is_default_for_target=body.is_default_for_target,
    )
    updated = await repo.update(provider_id, update)
    assert updated is not None  # row existed; guarded above
    # ``enabled`` is not on the update DTO — set it directly when provided.
    if body.enabled is not None:
        updated.enabled = body.enabled
        await session.flush()
    await session.commit()
    await session.refresh(updated)
    return _row_to_detail(updated)


@router.delete("/mcp/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_provider(
    provider_id: str,
    ctx: TenantContext = Depends(require_role(_WRITE_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete a custom provider. Builtins are read-only (409)."""
    if provider_id.startswith(_BUILTIN_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="bundled providers are read-only"
        )
    repo = McpProviderRepo(session)
    row = await repo.get_by_id(provider_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="provider not found")
    await repo.delete(provider_id)
    await session.commit()
