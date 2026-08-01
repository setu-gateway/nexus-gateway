from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.db.models import Project
from apps.gateway.db.session import get_db_session

router = APIRouter(prefix="/projects", tags=["Projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Project name")
    organization_id: str = Field(description="Associated organization UUID")
    description: Optional[str] = Field(default=None, description="Optional project description")


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None)


class ProjectResponse(BaseModel):
    id: str
    name: str
    organization_id: str
    description: Optional[str]
    created_at: datetime


def _to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        organization_id=str(project.organization_id),
        description=project.description,
        created_at=project.created_at,
    )


async def _get_project_or_404(id: str, db: AsyncSession) -> Project:
    try:
        project_id = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{id}' not found")
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{id}' not found")
    return project


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    organization_id: Optional[str] = Query(None, description="Filter by organization ID"),
    db: AsyncSession = Depends(get_db_session),
) -> List[ProjectResponse]:
    """List projects, optionally filtered by organization_id."""
    query = select(Project)
    if organization_id:
        try:
            query = query.where(Project.organization_id == uuid.UUID(organization_id))
        except ValueError:
            return []
    result = await db.execute(query)
    return [_to_response(p) for p in result.scalars().all()]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(req: ProjectCreate, db: AsyncSession = Depends(get_db_session)) -> ProjectResponse:
    """Create a new project linked to an organization."""
    try:
        organization_id = uuid.UUID(req.organization_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id must be a valid UUID")

    project = Project(id=uuid.uuid4(), name=req.name, organization_id=organization_id, description=req.description)
    db.add(project)
    await db.flush()
    return _to_response(project)


@router.get("/{id}", response_model=ProjectResponse)
async def get_project(id: str, db: AsyncSession = Depends(get_db_session)) -> ProjectResponse:
    """Retrieve a project by ID."""
    project = await _get_project_or_404(id, db)
    return _to_response(project)


@router.patch("/{id}", response_model=ProjectResponse)
async def update_project(
    id: str, req: ProjectUpdate, db: AsyncSession = Depends(get_db_session)
) -> ProjectResponse:
    """Update project attributes."""
    project = await _get_project_or_404(id, db)

    if req.name is not None:
        project.name = req.name
    if req.description is not None:
        project.description = req.description

    await db.flush()
    return _to_response(project)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_project(id: str, db: AsyncSession = Depends(get_db_session)) -> dict:
    """Delete a project by ID."""
    project = await _get_project_or_404(id, db)
    await db.delete(project)
    return {"message": f"Project '{id}' deleted successfully"}
