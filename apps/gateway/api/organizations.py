from datetime import datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/organizations", tags=["Organizations"])

# In-memory store stub (syncs with Database models in full execution)
_organizations_db_stub: dict[str, dict] = {}


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
    return name.lower().replace(" ", "-").replace("_", "-")


@router.get("", response_model=List[OrganizationResponse])
async def list_organizations() -> List[OrganizationResponse]:
    """List all organizations."""
    return [OrganizationResponse(**org) for org in _organizations_db_stub.values()]


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(req: OrganizationCreate) -> OrganizationResponse:
    """Create a new organization."""
    org_id = str(uuid.uuid4())
    slug = req.slug or _slugify(req.name)

    # Check slug uniqueness
    for org in _organizations_db_stub.values():
        if org["slug"] == slug:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization with slug '{slug}' already exists",
            )

    now = datetime.now(timezone.utc)
    org_record = {
        "id": org_id,
        "name": req.name,
        "slug": slug,
        "plan": req.plan or "free",
        "created_at": now,
        "updated_at": now,
    }

    _organizations_db_stub[org_id] = org_record
    return OrganizationResponse(**org_record)


@router.get("/{id}", response_model=OrganizationResponse)
async def get_organization(id: str) -> OrganizationResponse:
    """Retrieve an organization by ID."""
    org = _organizations_db_stub.get(id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization '{id}' not found",
        )
    return OrganizationResponse(**org)


@router.patch("/{id}", response_model=OrganizationResponse)
async def update_organization(id: str, req: OrganizationUpdate) -> OrganizationResponse:
    """Update organization attributes."""
    org = _organizations_db_stub.get(id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization '{id}' not found",
        )

    if req.name is not None:
        org["name"] = req.name
    if req.slug is not None:
        # Check slug collision
        for existing_id, existing_org in _organizations_db_stub.items():
            if existing_id != id and existing_org["slug"] == req.slug:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Organization with slug '{req.slug}' already exists",
                )
        org["slug"] = req.slug
    if req.plan is not None:
        org["plan"] = req.plan

    org["updated_at"] = datetime.now(timezone.utc)
    return OrganizationResponse(**org)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_organization(id: str) -> dict:
    """Delete an organization by ID."""
    org = _organizations_db_stub.pop(id, None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization '{id}' not found",
        )
    return {"message": f"Organization '{id}' deleted successfully"}
