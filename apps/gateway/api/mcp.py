import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.audit import record_audit_event
from apps.gateway.auth import (
    DashboardUserContext,
    KeyPermission,
    Permission,
    require_permission,
    resolve_auth_or_401,
    resolve_dashboard_user_or_401,
)
from apps.gateway.db.models import MCPServer
from apps.gateway.db.session import get_db_session
from apps.gateway.mcp import MCPError, call_tool, check_health, list_tools
from apps.gateway.utils import fire_and_forget

router = APIRouter(prefix="/mcp", tags=["MCP"])


def _audit_ctx(request: Request) -> dict:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


def _validate_url(v: str) -> str:
    if not v.startswith("http://") and not v.startswith("https://"):
        raise ValueError("url must start with http:// or https://")
    return v


class MCPServerCreate(BaseModel):
    organization_id: str
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(description="The server's MCP (Streamable HTTP) endpoint URL")
    description: str | None = None
    headers: dict[str, str] | None = Field(default=None, description="Extra headers (e.g. Authorization) sent on every call")
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _validate_url_field(cls, v: str) -> str:
        return _validate_url(v)


class MCPServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = None
    description: str | None = None
    headers: dict[str, str] | None = None
    enabled: bool | None = None

    @field_validator("url")
    @classmethod
    def _validate_url_field(cls, v: str | None) -> str | None:
        return _validate_url(v) if v is not None else v


class MCPServerResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    url: str
    description: str | None
    enabled: bool
    last_health_status: str | None
    last_health_checked_at: datetime | None
    last_health_error: str | None
    created_at: datetime
    updated_at: datetime
    # `headers` deliberately never echoed back in any response - it may carry a
    # credential for the external MCP server, and the caller who set it already
    # knows its value, so there's no need for the gateway to redisplay it.


class MCPToolResponse(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict[str, Any] | None = Field(default=None, alias="inputSchema")

    model_config = {"populate_by_name": True}


class MCPToolsResponse(BaseModel):
    tools: list[MCPToolResponse]


class MCPToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPToolCallResponse(BaseModel):
    content: list[dict[str, Any]] = Field(default_factory=list)
    is_error: bool = Field(default=False, alias="isError")

    model_config = {"populate_by_name": True}


def _to_response(server: MCPServer) -> MCPServerResponse:
    return MCPServerResponse(
        id=str(server.id),
        organization_id=str(server.organization_id),
        name=server.name,
        url=server.url,
        description=server.description,
        enabled=server.enabled,
        last_health_status=server.last_health_status,
        last_health_checked_at=server.last_health_checked_at,
        last_health_error=server.last_health_error,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


async def _get_server_or_404(server_id: str, db: AsyncSession, user: DashboardUserContext | None = None) -> MCPServer:
    """user is only passed by the dashboard-management endpoints below, which enforce
    tenant isolation. call_mcp_server_tool's API-key path (further down) has never
    been tenant-scoped by organization - it's a separate, existing auth mechanism
    (KeyPermission.MCP_INVOKE) not being changed here - so it omits user."""
    try:
        server_uuid = uuid.UUID(server_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid MCP server id: '{server_id}'") from None
    server = await db.get(MCPServer, server_uuid)
    if not server or (user is not None and not user.owns_organization(str(server.organization_id))):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"MCP server '{server_id}' not found")
    return server


@router.post("/servers", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    req: MCPServerCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_MCP_SERVERS)),
) -> MCPServerResponse:
    if not user.owns_organization(req.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create an MCP server for another organization")
    server = MCPServer(
        id=uuid.uuid4(),
        organization_id=uuid.UUID(req.organization_id),
        name=req.name,
        url=req.url,
        description=req.description,
        headers=req.headers,
        enabled=req.enabled,
    )
    db.add(server)
    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="mcp_server.created",
            resource_type="mcp_server",
            resource_id=str(server.id),
            organization_id=str(server.organization_id),
            details={"name": server.name, "url": server.url},
            **_audit_ctx(request),
        )
    )
    return _to_response(server)


@router.get("/servers", response_model=list[MCPServerResponse])
async def list_mcp_servers(
    organization_id: str = Query(description="Organization UUID to list MCP servers for"),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[MCPServerResponse]:
    if not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot list MCP servers for another organization")
    result = await db.execute(
        select(MCPServer).where(MCPServer.organization_id == uuid.UUID(organization_id)).order_by(MCPServer.created_at.desc())
    )
    return [_to_response(s) for s in result.scalars().all()]


@router.get("/servers/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> MCPServerResponse:
    server = await _get_server_or_404(server_id, db, user)
    return _to_response(server)


@router.patch("/servers/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: str,
    req: MCPServerUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_MCP_SERVERS)),
) -> MCPServerResponse:
    server = await _get_server_or_404(server_id, db, user)
    if req.name is not None:
        server.name = req.name
    if req.url is not None:
        server.url = req.url
    if req.description is not None:
        server.description = req.description
    if req.headers is not None:
        server.headers = req.headers
    if req.enabled is not None:
        server.enabled = req.enabled
    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="mcp_server.updated",
            resource_type="mcp_server",
            resource_id=str(server.id),
            organization_id=str(server.organization_id),
            details=req.model_dump(exclude_none=True, exclude={"headers"}),
            **_audit_ctx(request),
        )
    )
    return _to_response(server)


@router.delete("/servers/{server_id}", status_code=status.HTTP_200_OK)
async def delete_mcp_server(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_MCP_SERVERS)),
) -> dict:
    server = await _get_server_or_404(server_id, db, user)
    organization_id = str(server.organization_id)
    await db.delete(server)

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="mcp_server.deleted",
            resource_type="mcp_server",
            resource_id=server_id,
            organization_id=organization_id,
            **_audit_ctx(request),
        )
    )
    return {"message": f"MCP server '{server_id}' deleted successfully"}


def _disabled_error(server: MCPServer) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"MCP server '{server.name}' is disabled")


@router.post("/servers/{server_id}/health", response_model=MCPServerResponse)
async def check_mcp_server_health(
    server_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> MCPServerResponse:
    """Sends an MCP `initialize` request now and persists the outcome - an on-demand
    check (e.g. dashboard "test connection" button), not a continuous poller."""
    server = await _get_server_or_404(server_id, db, user)
    if not server.enabled:
        raise _disabled_error(server)

    try:
        await check_health(server.url, server.headers)
        server.last_health_status = "ok"
        server.last_health_error = None
    except MCPError as e:
        server.last_health_status = "error"
        server.last_health_error = str(e)
    server.last_health_checked_at = datetime.now(timezone.utc)
    await db.flush()
    return _to_response(server)


@router.get("/servers/{server_id}/tools", response_model=MCPToolsResponse)
async def get_mcp_server_tools(
    server_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> MCPToolsResponse:
    """Live tool discovery (`tools/list`) - not cached, since a server's tools can
    change between calls."""
    server = await _get_server_or_404(server_id, db, user)
    if not server.enabled:
        raise _disabled_error(server)

    try:
        tools = await list_tools(server.url, server.headers)
    except MCPError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"MCP server '{server.name}': {e}") from e
    return MCPToolsResponse(tools=[MCPToolResponse.model_validate(t) for t in tools])


@router.post("/servers/{server_id}/tools/{tool_name}/call", response_model=MCPToolCallResponse)
async def call_mcp_server_tool(
    server_id: str,
    tool_name: str,
    req: MCPToolCallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    authorization: str | None = Header(default=None),
) -> MCPToolCallResponse:
    """Invokes a tool on a registered MCP server. Unlike the read-only server/tool
    management endpoints above, this executes real work against an external system,
    so - like /v1/chat/completions - it enforces the 'mcp_invoke' permission when a
    scoped API key is presented (auth remains optional, same reasoning as chat/
    embeddings: making it mandatory here is a bigger, separate decision)."""
    client_ip = request.client.host if request.client else None
    await resolve_auth_or_401(db, authorization, client_ip, KeyPermission.MCP_INVOKE)

    server = await _get_server_or_404(server_id, db)
    if not server.enabled:
        raise _disabled_error(server)

    try:
        result = await call_tool(server.url, tool_name, req.arguments, server.headers)
    except MCPError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"MCP server '{server.name}': {e}") from e

    fire_and_forget(
        record_audit_event(
            actor="anonymous",
            action="mcp_tool.called",
            resource_type="mcp_server",
            resource_id=str(server.id),
            organization_id=str(server.organization_id),
            details={"tool_name": tool_name},
            **_audit_ctx(request),
        )
    )
    return MCPToolCallResponse.model_validate(result)
