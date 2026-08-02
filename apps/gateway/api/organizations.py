import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.audit import record_audit_event
from apps.gateway.auth import DashboardUserContext, Role, require_role, resolve_dashboard_user_or_401
from apps.gateway.db.models import Organization, RequestLog
from apps.gateway.db.session import get_db_session
from apps.gateway.utils import fire_and_forget

router = APIRouter(prefix="/organizations", tags=["Organizations"])


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Organization name")
    slug: str | None = Field(default=None, description="URL-friendly slug (auto-generated if empty)")
    plan: str | None = Field(default="free", description="Subscription plan")
    monthly_request_quota: int | None = Field(default=None, ge=0, description="Requests/month before over-quota. Null = unlimited.")
    monthly_spend_quota_usd: float | None = Field(default=None, ge=0, description="USD/month before over-quota. Null = unlimited.")


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None)
    plan: str | None = Field(default=None)
    monthly_request_quota: int | None = Field(default=None, ge=0)
    monthly_spend_quota_usd: float | None = Field(default=None, ge=0)


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    monthly_request_quota: int | None
    monthly_spend_quota_usd: float | None
    created_at: datetime
    updated_at: datetime


class OrganizationUsageResponse(BaseModel):
    organization_id: str
    period_start: datetime
    requests_used: int
    estimated_cost_used: float
    monthly_request_quota: int | None
    monthly_spend_quota_usd: float | None
    requests_remaining: int | None
    spend_remaining_usd: float | None
    is_over_request_quota: bool
    is_over_spend_quota: bool


def _slugify(name: str) -> str:
    """Generate a clean URL slug from name."""
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "org"


def _to_response(org: Organization) -> OrganizationResponse:
    return OrganizationResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        monthly_request_quota=org.monthly_request_quota,
        monthly_spend_quota_usd=org.monthly_spend_quota_usd,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


async def _get_org_or_404(id: str, db: AsyncSession, user: DashboardUserContext) -> Organization:
    """Fetches the organization by id, but only if it's the caller's own - a
    cross-tenant lookup is reported as 404, not 403, so a caller can't use this
    endpoint to confirm whether some other organization's id even exists."""
    try:
        org_id = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization '{id}' not found") from None
    if not user.owns_organization(str(org_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization '{id}' not found")
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization '{id}' not found")
    return org


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> list[OrganizationResponse]:
    """List the caller's own organization. There's no cross-org visibility today - a
    user belongs to exactly one organization - so this returns at most one entry."""
    if not user.organization_id:
        return []
    result = await db.execute(select(Organization).where(Organization.id == uuid.UUID(user.organization_id)))
    return [_to_response(o) for o in result.scalars().all()]


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    req: OrganizationCreate,
    db: AsyncSession = Depends(get_db_session),
    _user: DashboardUserContext = Depends(require_role(Role.OWNER)),
) -> OrganizationResponse:
    """Create an additional, standalone organization. This is an ops/admin
    capability, not the normal signup path - a new user's own organization is
    created for them by POST /auth/register."""
    slug = req.slug or _slugify(req.name)

    existing = await db.execute(select(Organization).where(Organization.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Organization with slug '{slug}' already exists",
        )

    org = Organization(
        id=uuid.uuid4(),
        name=req.name,
        slug=slug,
        plan=req.plan or "free",
        monthly_request_quota=req.monthly_request_quota,
        monthly_spend_quota_usd=req.monthly_spend_quota_usd,
    )
    db.add(org)
    await db.flush()
    return _to_response(org)


@router.get("/{id}", response_model=OrganizationResponse)
async def get_organization(
    id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> OrganizationResponse:
    """Retrieve an organization by ID."""
    org = await _get_org_or_404(id, db, user)
    return _to_response(org)


@router.patch("/{id}", response_model=OrganizationResponse)
async def update_organization(
    id: str,
    req: OrganizationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_role(Role.ADMIN)),
) -> OrganizationResponse:
    """Update organization attributes."""
    org = await _get_org_or_404(id, db, user)

    if req.slug is not None and req.slug != org.slug:
        existing = await db.execute(select(Organization).where(Organization.slug == req.slug))
        conflict = existing.scalar_one_or_none()
        if conflict is not None and conflict.id != org.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization with slug '{req.slug}' already exists",
            )
        org.slug = req.slug
    if req.name is not None:
        org.name = req.name
    if req.plan is not None:
        org.plan = req.plan
    if req.monthly_request_quota is not None:
        org.monthly_request_quota = req.monthly_request_quota
    if req.monthly_spend_quota_usd is not None:
        org.monthly_spend_quota_usd = req.monthly_spend_quota_usd

    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="organization.updated",
            resource_type="organization",
            resource_id=str(org.id),
            organization_id=str(org.id),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            details=req.model_dump(exclude_none=True),
        )
    )

    return _to_response(org)


@router.get("/{id}/usage", response_model=OrganizationUsageResponse)
async def get_organization_usage(
    id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> OrganizationUsageResponse:
    """Current calendar-month usage vs quota (Epic 5.6 - billing foundation). Tracking
    and visibility only: an organization over quota is flagged here for the dashboard/
    billing system to act on, but the gateway itself never rejects a request for it -
    that's payment enforcement, a deliberately separate, later decision."""
    org = await _get_org_or_404(id, db, user)

    period_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    totals_query = select(func.count(RequestLog.id), func.sum(RequestLog.estimated_cost)).where(
        RequestLog.organization_id == org.id, RequestLog.created_at >= period_start
    )
    requests_used, cost_used = (await db.execute(totals_query)).one()
    requests_used = requests_used or 0
    cost_used = cost_used or 0.0

    requests_remaining = max(0, org.monthly_request_quota - requests_used) if org.monthly_request_quota is not None else None
    spend_remaining = max(0.0, org.monthly_spend_quota_usd - cost_used) if org.monthly_spend_quota_usd is not None else None

    return OrganizationUsageResponse(
        organization_id=str(org.id),
        period_start=period_start,
        requests_used=requests_used,
        estimated_cost_used=round(cost_used, 6),
        monthly_request_quota=org.monthly_request_quota,
        monthly_spend_quota_usd=org.monthly_spend_quota_usd,
        requests_remaining=requests_remaining,
        spend_remaining_usd=round(spend_remaining, 6) if spend_remaining is not None else None,
        is_over_request_quota=org.monthly_request_quota is not None and requests_used > org.monthly_request_quota,
        is_over_spend_quota=org.monthly_spend_quota_usd is not None and cost_used > org.monthly_spend_quota_usd,
    )


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_organization(
    id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(require_role(Role.OWNER))
) -> dict:
    """Delete an organization by ID."""
    org = await _get_org_or_404(id, db, user)
    await db.delete(org)
    return {"message": f"Organization '{id}' deleted successfully"}
