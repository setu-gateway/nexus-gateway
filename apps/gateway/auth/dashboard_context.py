import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth.rbac import Permission, Role, has_permission, has_role_at_least
from apps.gateway.auth.security import decode_token
from apps.gateway.auth.token_blacklist import is_blacklisted
from apps.gateway.db.models import User
from apps.gateway.db.session import get_db_session


@dataclass
class DashboardUserContext:
    user_id: str
    email: str
    organization_id: str | None
    role: str
    is_verified: bool

    def has_permission(self, required: Permission) -> bool:
        return has_permission(self.role, required)

    def has_role_at_least(self, required_role: Role) -> bool:
        return has_role_at_least(self.role, required_role)

    def owns_organization(self, organization_id: str | None) -> bool:
        """Tenant-isolation check: does this user belong to the organization that
        owns the resource being accessed? Every management endpoint that reads or
        mutates an org-scoped resource must check this in addition to role/permission
        - a sufficient role only proves the caller is privileged *somewhere*, not that
        they're privileged for *this* organization's data."""
        return organization_id is not None and self.organization_id == organization_id


async def resolve_dashboard_user_or_401(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardUserContext:
    """Resolves a dashboard-session Bearer JWT (issued by POST /auth/login) to the
    authenticated user. Unlike resolve_auth_or_401 (API keys, optional on most
    endpoints), dashboard-management endpoints have no anonymous mode - a missing,
    malformed, expired, revoked, or otherwise invalid token is always a 401.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or malformed Authorization header")

    token = authorization.split(" ", 1)[1].strip()
    if is_blacklisted(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")

    try:
        payload = decode_token(token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type for authorization")

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token subject") from e

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    return DashboardUserContext(
        user_id=str(user.id),
        email=user.email,
        organization_id=str(user.organization_id) if user.organization_id else None,
        role=user.role,
        is_verified=user.is_verified,
    )


def require_permission(required_permission: Permission) -> Callable:
    """FastAPI dependency: resolves the caller and enforces a specific permission.
    Returns the resolved user so callers can also do their own tenant-isolation check
    (owns_organization) against the resource they're about to read or mutate."""

    async def checker(
        user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
    ) -> DashboardUserContext:
        if not user.has_permission(required_permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: requires '{required_permission.value}' permission",
            )
        return user

    return checker


def require_role(required_role: Role) -> Callable:
    """FastAPI dependency: resolves the caller and enforces a minimum role rank."""

    async def checker(
        user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
    ) -> DashboardUserContext:
        if not user.has_role_at_least(required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role permission denied: requires at least '{required_role.value}' role",
            )
        return user

    return checker
