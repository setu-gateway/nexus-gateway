from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth.api_key import hash_api_key
from apps.gateway.auth.permissions import has_key_permission, ip_allowed
from apps.gateway.auth.security import decode_token
from apps.gateway.db.models import APIKey, Project


@dataclass
class RequestAuthContext:
    api_key_id: str
    project_id: str
    organization_id: str
    permissions: list[str] | None = None
    allowed_providers: list[str] | None = None
    allowed_models: list[str] | None = None
    rate_limit_per_minute: int | None = None

    def has_permission(self, required: str) -> bool:
        return has_key_permission(self.permissions, required)


async def resolve_api_key(db: AsyncSession, authorization_header: str | None, client_ip: str | None = None) -> RequestAuthContext | None:
    """Resolve a Bearer API key to its owning project/organization (RFC-0007: scoped
    API keys as the tenant-resolution mechanism). Returns None if no key was
    presented, the key is missing/revoked/expired, or (Epic 5.3) `client_ip` isn't on
    the key's IP allowlist - callers decide whether that's acceptable. These endpoints
    don't *require* auth yet (see apps/gateway/api/openai_v1.py): making it mandatory
    is a bigger, separate decision that would break the current playground/quickstart/
    test flows, which all call the API unauthenticated today.
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None

    plaintext_key = authorization_header.split(" ", 1)[1].strip()
    if not plaintext_key:
        return None

    hashed = hash_api_key(plaintext_key)
    result = await db.execute(select(APIKey).where(APIKey.hashed_key == hashed))
    key = result.scalar_one_or_none()

    if not key or key.revoked_at is not None:
        return None
    if key.expires_at is not None and key.expires_at < datetime.now(timezone.utc):
        return None
    if not ip_allowed(key.allowed_ips, client_ip):
        return None

    project_result = await db.execute(select(Project).where(Project.id == key.project_id))
    project = project_result.scalar_one_or_none()
    if not project:
        return None

    key.last_used_at = datetime.now(timezone.utc)

    return RequestAuthContext(
        api_key_id=str(key.id),
        project_id=str(key.project_id),
        organization_id=str(project.organization_id),
        permissions=key.permissions,
        allowed_providers=key.allowed_providers,
        allowed_models=key.allowed_models,
        rate_limit_per_minute=key.rate_limit_per_minute,
    )


def _is_dashboard_access_token(authorization_header: str) -> bool:
    """A dashboard session JWT (issued by POST /auth/login) is a Bearer token shape
    too, but it's not a scoped API key - resolve_api_key's hash lookup will never
    find it in the APIKey table. Recognized here so resolve_auth_or_401 can treat it
    as "no scoped key to enforce" instead of "an invalid key was presented"."""
    token = authorization_header.split(" ", 1)[1].strip()
    try:
        return decode_token(token).get("type") == "access"
    except ValueError:
        return False


async def resolve_auth_or_401(
    db: AsyncSession,
    authorization_header: str | None,
    client_ip: str | None,
    required_permission: str | None = None,
) -> RequestAuthContext | None:
    """resolve_api_key, plus the two checks every optionally-authenticated endpoint
    (chat/embeddings/models/MCP tool calls) layers on top of it: a *presented* Bearer
    key that didn't resolve is a real 401, not silently anonymous access, and a key
    that resolved but lacks `required_permission` is a 403. Returns None for the
    "no key presented at all" case (the caller decides whether that's acceptable for
    the endpoint in question) and also for a presented dashboard session JWT, which
    carries no scoped-key permissions/allowlists to enforce here.
    """
    if authorization_header and authorization_header.startswith("Bearer ") and _is_dashboard_access_token(authorization_header):
        return None

    auth_context = await resolve_api_key(db, authorization_header, client_ip)
    if authorization_header and authorization_header.startswith("Bearer ") and auth_context is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key is invalid, revoked, or expired")
    if auth_context and required_permission and not auth_context.has_permission(required_permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"This API key does not have '{required_permission}' permission")
    return auth_context
