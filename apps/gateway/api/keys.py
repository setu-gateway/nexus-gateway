import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.audit import record_audit_event
from apps.gateway.auth.api_key import generate_api_key, mask_api_key
from apps.gateway.auth.context import resolve_api_key
from apps.gateway.auth.dashboard_context import resolve_dashboard_user_or_401
from apps.gateway.auth.permissions import KeyPermission
from apps.gateway.auth.rbac import Permission
from apps.gateway.db.models import APIKey, Project
from apps.gateway.db.session import get_db_session
from apps.gateway.utils import fire_and_forget
from apps.gateway.webhooks import WebhookEvent, dispatch_webhook_event

router = APIRouter(prefix="/keys", tags=["API Keys"])


async def _resolve_organization_id_for_project(db: AsyncSession, project_id: uuid.UUID) -> str | None:
    result = await db.execute(select(Project.organization_id).where(Project.id == project_id))
    org_id = result.scalar_one_or_none()
    return str(org_id) if org_id else None


class ApiKeyCreateRequest(BaseModel):
    project_id: str = Field(description="Associated project UUID")
    name: str = Field(default="Default Key", description="Human readable key label")
    expires_at: datetime | None = Field(default=None, description="Optional key expiration timestamp")
    permissions: list[str] | None = Field(
        default=None, description="Allowed operations (chat/embeddings/models_read/analytics_read/admin). Omit for full access."
    )
    allowed_ips: list[str] | None = Field(default=None, description="IP addresses/CIDR ranges this key may be used from")
    allowed_providers: list[str] | None = Field(default=None, description="Provider names this key may route to")
    allowed_models: list[str] | None = Field(default=None, description="Upstream model ids this key may request")
    rate_limit_per_minute: int | None = Field(default=None, ge=1, description="Per-key request budget")

    @field_validator("allowed_ips")
    @classmethod
    def _validate_allowed_ips(cls, ips: list[str] | None) -> list[str] | None:
        if not ips:
            return ips
        for entry in ips:
            try:
                ip_network(entry, strict=False) if "/" in entry else ip_address(entry)
            except ValueError:
                raise ValueError(f"'{entry}' is not a valid IP address or CIDR range") from None
        return ips

    @field_validator("permissions")
    @classmethod
    def _validate_permissions(cls, permissions: list[str] | None) -> list[str] | None:
        if not permissions:
            return permissions
        unknown = set(permissions) - KeyPermission.ALL
        if unknown:
            raise ValueError(f"Unknown permission(s): {', '.join(sorted(unknown))}. Valid: {', '.join(sorted(KeyPermission.ALL))}")
        return permissions


class ApiKeyCreatedResponse(BaseModel):
    id: str
    name: str
    project_id: str
    key: str = Field(description="Plaintext API key - shown ONLY ONCE on creation!")
    masked_key: str
    expires_at: datetime | None
    permissions: list[str] | None
    allowed_ips: list[str] | None
    allowed_providers: list[str] | None
    allowed_models: list[str] | None
    rate_limit_per_minute: int | None
    created_at: datetime


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    project_id: str
    masked_key: str
    last_used_at: datetime | None
    expires_at: datetime | None
    permissions: list[str] | None
    allowed_ips: list[str] | None
    allowed_providers: list[str] | None
    allowed_models: list[str] | None
    rate_limit_per_minute: int | None
    created_at: datetime


def _to_response(key: APIKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=str(key.id),
        name=key.name,
        project_id=str(key.project_id),
        masked_key=key.masked_key,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        permissions=key.permissions,
        allowed_ips=key.allowed_ips,
        allowed_providers=key.allowed_providers,
        allowed_models=key.allowed_models,
        rate_limit_per_minute=key.rate_limit_per_minute,
        created_at=key.created_at,
    )


async def _get_active_key_or_404(id: str, db: AsyncSession) -> APIKey:
    try:
        key_id = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API key '{id}' not found") from None
    result = await db.execute(select(APIKey).where(APIKey.id == key_id, APIKey.revoked_at.is_(None)))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API key '{id}' not found")
    return key


@dataclass
class _KeyManagementActor:
    actor: str
    # None for an API-key-based caller (pre-existing behavior, unchanged: an
    # admin-scoped key's own cross-org reach was never tenant-constrained here).
    # Set for a dashboard user, so callers can enforce that they only manage keys
    # belonging to their own organization's projects.
    organization_id: str | None


async def _require_admin(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    authorization: str | None = Header(default=None),
) -> _KeyManagementActor:
    """Key management requires either a scoped API key with the 'admin' permission
    (CLI/automation use that isn't going through the dashboard) or a logged-in
    dashboard user with the manage_api_keys permission. Presenting neither is a 401 -
    unlike before, there's no anonymous fallback."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or malformed Authorization header")

    token = authorization.split(" ", 1)[1].strip()
    if token.startswith("sk_setu_"):
        client_ip = request.client.host if request.client else None
        auth_context = await resolve_api_key(db, authorization, client_ip)
        if auth_context is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key is invalid, revoked, or expired")
        if not auth_context.has_permission(KeyPermission.ADMIN):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This API key does not have 'admin' permission")
        return _KeyManagementActor(actor=f"api_key:{auth_context.api_key_id}", organization_id=None)

    user = await resolve_dashboard_user_or_401(authorization=authorization, db=db)
    if not user.has_permission(Permission.MANAGE_API_KEYS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires 'manage_api_keys' permission")
    return _KeyManagementActor(actor=f"user:{user.user_id}", organization_id=user.organization_id)


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    req: ApiKeyCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    actor: _KeyManagementActor = Depends(_require_admin),
) -> ApiKeyCreatedResponse:
    """Generate a secure API key (sk_setu_...). Stores ONLY the SHA-256 hash in DB."""
    client_ip = request.client.host if request.client else None

    try:
        project_id = uuid.UUID(req.project_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id must be a valid UUID") from None

    organization_id = await _resolve_organization_id_for_project(db, project_id)
    if actor.organization_id is not None and actor.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{req.project_id}' not found")

    plaintext_key, hashed_key = generate_api_key(prefix="sk_setu_")
    masked = mask_api_key(plaintext_key)

    key = APIKey(
        id=uuid.uuid4(),
        project_id=project_id,
        name=req.name,
        hashed_key=hashed_key,
        masked_key=masked,
        expires_at=req.expires_at,
        permissions=req.permissions,
        allowed_ips=req.allowed_ips,
        allowed_providers=req.allowed_providers,
        allowed_models=req.allowed_models,
        rate_limit_per_minute=req.rate_limit_per_minute,
    )
    db.add(key)
    await db.flush()

    fire_and_forget(
        dispatch_webhook_event(
            organization_id, WebhookEvent.KEY_CREATED, {"api_key_id": str(key.id), "project_id": str(project_id), "name": key.name}
        )
    )
    fire_and_forget(
        record_audit_event(
            actor=actor.actor,
            action="key.created",
            resource_type="api_key",
            resource_id=str(key.id),
            organization_id=organization_id,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            details={"project_id": str(project_id), "name": key.name},
        )
    )

    return ApiKeyCreatedResponse(
        id=str(key.id),
        name=key.name,
        project_id=str(key.project_id),
        key=plaintext_key,
        masked_key=masked,
        expires_at=key.expires_at,
        permissions=key.permissions,
        allowed_ips=key.allowed_ips,
        allowed_providers=key.allowed_providers,
        allowed_models=key.allowed_models,
        rate_limit_per_minute=key.rate_limit_per_minute,
        created_at=key.created_at,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    project_id: str | None = Query(None, description="Filter by project ID"),
    db: AsyncSession = Depends(get_db_session),
    actor: _KeyManagementActor = Depends(_require_admin),
) -> list[ApiKeyResponse]:
    """List active (non-revoked) API keys, masked for safety. Plaintext keys are never returned."""
    query = select(APIKey).where(APIKey.revoked_at.is_(None))
    if project_id:
        try:
            query = query.where(APIKey.project_id == uuid.UUID(project_id))
        except ValueError:
            return []
    if actor.organization_id is not None:
        query = query.join(Project, Project.id == APIKey.project_id).where(Project.organization_id == uuid.UUID(actor.organization_id))
    result = await db.execute(query)
    return [_to_response(k) for k in result.scalars().all()]


async def _get_active_key_or_404_for_actor(id: str, db: AsyncSession, actor: _KeyManagementActor) -> APIKey:
    key = await _get_active_key_or_404(id, db)
    if actor.organization_id is not None:
        organization_id = await _resolve_organization_id_for_project(db, key.project_id)
        if organization_id != actor.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API key '{id}' not found")
    return key


@router.get("/{id}", response_model=ApiKeyResponse)
async def get_api_key(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    actor: _KeyManagementActor = Depends(_require_admin),
) -> ApiKeyResponse:
    """Retrieve API key metadata by ID."""
    key = await _get_active_key_or_404_for_actor(id, db, actor)
    return _to_response(key)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def revoke_api_key(
    id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    actor: _KeyManagementActor = Depends(_require_admin),
) -> dict:
    """Revoke an API key. Soft-deleted (revoked_at set) rather than removed outright,
    so a compromised-key incident leaves an audit trail (RFC-0008)."""
    client_ip = request.client.host if request.client else None
    key = await _get_active_key_or_404_for_actor(id, db, actor)
    key.revoked_at = datetime.now(timezone.utc)
    await db.flush()

    organization_id = await _resolve_organization_id_for_project(db, key.project_id)
    fire_and_forget(
        dispatch_webhook_event(organization_id, WebhookEvent.KEY_REVOKED, {"api_key_id": str(key.id), "project_id": str(key.project_id)})
    )
    fire_and_forget(
        record_audit_event(
            actor=actor.actor,
            action="key.revoked",
            resource_type="api_key",
            resource_id=str(key.id),
            organization_id=organization_id,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
        )
    )

    return {"message": f"API key '{id}' revoked successfully"}
