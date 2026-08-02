import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.audit import record_audit_event
from apps.gateway.auth.dashboard_context import DashboardUserContext, resolve_dashboard_user_or_401
from apps.gateway.auth.rbac import Role
from apps.gateway.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_email_address,
    verify_password,
)
from apps.gateway.auth.token_blacklist import blacklist_token, is_blacklisted
from apps.gateway.db.models import Organization, Project, User
from apps.gateway.db.session import get_db_session
from apps.gateway.utils import fire_and_forget

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _slugify(name: str) -> str:
    """Generate a clean URL slug from an organization name."""
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "org"


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="User password (min 8 chars)")
    organization_name: str | None = "Default Org"


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    is_verified: bool
    is_active: bool
    role: str
    organization_id: str | None = None


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(req: UserRegisterRequest, db: AsyncSession = Depends(get_db_session)) -> UserResponse:
    """Register a new user account with a personal organization and default project."""
    if not validate_email_address(req.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email address format",
        )

    email = req.email.lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )

    org_name = req.organization_name or "Personal Organization"
    organization = Organization(
        id=uuid.uuid4(),
        name=org_name,
        slug=f"{_slugify(org_name)}-{uuid.uuid4().hex[:8]}",
        plan="free",
    )
    project = Project(
        id=uuid.uuid4(),
        name="Default Project",
        organization_id=organization.id,
    )
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(req.password),
        is_verified=False,
        is_active=True,
        # Registration always creates a brand-new organization for this user (above) -
        # they're its sole member, so they're its owner. There's no "join an existing
        # organization" flow yet (that would need real invitations, which RFC-0003
        # scopes out for now - see Permission.INVITE_MEMBERS).
        role=Role.OWNER.value,
        organization_id=organization.id,
    )
    db.add_all([organization, project, user])

    return UserResponse(
        id=str(user.id),
        email=user.email,
        is_verified=user.is_verified,
        is_active=user.is_active,
        role=user.role,
        organization_id=str(organization.id),
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: UserLoginRequest, request: Request, db: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    """Authenticate credentials and issue JWT Access and Refresh Tokens."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    email = req.email.lower()

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        fire_and_forget(
            record_audit_event(
                actor=email,
                action="login.failure",
                resource_type="user",
                resource_id=str(user.id) if user else None,
                organization_id=str(user.organization_id) if user and user.organization_id else None,
                ip_address=client_ip,
                user_agent=user_agent,
                result="failure",
                details={"reason": "invalid_credentials"},
            )
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        fire_and_forget(
            record_audit_event(
                actor=email,
                action="login.failure",
                resource_type="user",
                resource_id=str(user.id),
                organization_id=str(user.organization_id) if user.organization_id else None,
                ip_address=client_ip,
                user_agent=user_agent,
                result="failure",
                details={"reason": "account_inactive"},
            )
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    fire_and_forget(
        record_audit_event(
            actor=email,
            action="login.success",
            resource_type="user",
            resource_id=str(user.id),
            organization_id=str(user.organization_id) if user.organization_id else None,
            ip_address=client_ip,
            user_agent=user_agent,
            result="success",
        )
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",  # nosec B106
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshTokenRequest, db: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    """Issue a new access and refresh token pair using a valid refresh token."""
    if is_blacklisted(req.refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    try:
        payload = decode_token(req.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token type, expected refresh token",
            )

        # Re-fetch the user rather than carrying the old token's claims forward: if
        # their role was downgraded or their account deactivated since this refresh
        # token was issued, that must take effect now, not after the refresh token's
        # own (much longer) expiry.
        user_id = payload.get("sub")
        result = await db.execute(select(User).where(User.id == uuid.UUID(str(user_id))))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
        new_access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data)

        blacklist_token(req.refresh_token)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",  # nosec B106
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e


@router.post("/logout")
async def logout(authorization: str | None = Header(None)) -> dict:
    """Revoke active JWT token session."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        blacklist_token(token)
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user(user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)) -> UserResponse:
    """Retrieve details for the currently authenticated user."""
    return UserResponse(
        id=user.user_id,
        email=user.email,
        is_verified=user.is_verified,
        is_active=True,
        role=user.role,
        organization_id=user.organization_id,
    )
