from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.db.models import Organization
from apps.gateway.db.session import get_db_session

router = APIRouter(prefix="/organizations", tags=["Organizations"])


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Organization name")
    slug: Optional[str] = Field(default=None, description="URL-friendly slug (auto-generated if empty)")
    plan: Optional[str] = Field(default="free", description="Subscription plan")


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None)
    plan: Optional[str] = Field(default=None)


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    created_at: datetime
    updated_at: datetime


def _slugify(name: str) -> str:
    """Generate a clean URL slug from name."""
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "org"


def _to_response(org: Organization) -> OrganizationResponse:
    return OrganizationResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


async def _get_org_or_404(id: str, db: AsyncSession) -> Organization:
    try:
        org_id = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization '{id}' not found")
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization '{id}' not found")
    return org


@router.get("", response_model=List[OrganizationResponse])
async def list_organizations(db: AsyncSession = Depends(get_db_session)) -> List[OrganizationResponse]:
    """List all organizations."""
    result = await db.execute(select(Organization))
    return [_to_response(o) for o in result.scalars().all()]


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    req: OrganizationCreate, db: AsyncSession = Depends(get_db_session)
) -> OrganizationResponse:
    """Create a new organization."""
    slug = req.slug or _slugify(req.name)

    existing = await db.execute(select(Organization).where(Organization.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Organization with slug '{slug}' already exists",
        )

    org = Organization(id=uuid.uuid4(), name=req.name, slug=slug, plan=req.plan or "free")
    db.add(org)
    await db.flush()
    return _to_response(org)


@router.get("/{id}", response_model=OrganizationResponse)
async def get_organization(id: str, db: AsyncSession = Depends(get_db_session)) -> OrganizationResponse:
    """Retrieve an organization by ID."""
    org = await _get_org_or_404(id, db)
    return _to_response(org)


@router.patch("/{id}", response_model=OrganizationResponse)
async def update_organization(
    id: str, req: OrganizationUpdate, db: AsyncSession = Depends(get_db_session)
) -> OrganizationResponse:
    """Update organization attributes."""
    org = await _get_org_or_404(id, db)

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

    await db.flush()
    return _to_response(org)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_organization(id: str, db: AsyncSession = Depends(get_db_session)) -> dict:
    """Delete an organization by ID."""
    org = await _get_org_or_404(id, db)
    await db.delete(org)
    return {"message": f"Organization '{id}' deleted successfully"}
