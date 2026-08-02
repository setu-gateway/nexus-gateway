import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth import DashboardUserContext, Permission, require_permission, resolve_dashboard_user_or_401
from apps.gateway.db.models import Project
from apps.gateway.db.session import get_db_session
from apps.gateway.utils import fire_and_forget
from apps.gateway.webhooks import WebhookEvent, dispatch_webhook_event

router = APIRouter(prefix="/projects", tags=["Projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Project name")
    organization_id: str = Field(description="Associated organization UUID")
    description: str | None = Field(default=None, description="Optional project description")


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None)


class ProjectResponse(BaseModel):
    id: str
    name: str
    organization_id: str
    description: str | None
    created_at: datetime


def _to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        organization_id=str(project.organization_id),
        description=project.description,
        created_at=project.created_at,
    )


async def _get_project_or_404(id: str, db: AsyncSession, user: DashboardUserContext) -> Project:
    try:
        project_id = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{id}' not found") from None
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project or not user.owns_organization(str(project.organization_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{id}' not found")
    return project


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    organization_id: str | None = Query(None, description="Filter by organization ID"),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[ProjectResponse]:
    """List projects belonging to the caller's own organization."""
    if organization_id and not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot list projects for another organization")
    if not user.organization_id:
        return []
    query = select(Project).where(Project.organization_id == uuid.UUID(user.organization_id))
    result = await db.execute(query)
    return [_to_response(p) for p in result.scalars().all()]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    req: ProjectCreate,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.CREATE_PROJECT)),
) -> ProjectResponse:
    """Create a new project linked to an organization."""
    if not user.owns_organization(req.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create a project for another organization")
    try:
        organization_id = uuid.UUID(req.organization_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id must be a valid UUID") from None

    project = Project(id=uuid.uuid4(), name=req.name, organization_id=organization_id, description=req.description)
    db.add(project)
    await db.flush()

    fire_and_forget(
        dispatch_webhook_event(str(organization_id), WebhookEvent.PROJECT_CREATED, {"project_id": str(project.id), "name": project.name})
    )

    return _to_response(project)


@router.get("/{id}", response_model=ProjectResponse)
async def get_project(
    id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> ProjectResponse:
    """Retrieve a project by ID."""
    project = await _get_project_or_404(id, db, user)
    return _to_response(project)


@router.patch("/{id}", response_model=ProjectResponse)
async def update_project(
    id: str,
    req: ProjectUpdate,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.CREATE_PROJECT)),
) -> ProjectResponse:
    """Update project attributes."""
    project = await _get_project_or_404(id, db, user)

    if req.name is not None:
        project.name = req.name
    if req.description is not None:
        project.description = req.description

    await db.flush()
    return _to_response(project)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_project(
    id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(require_permission(Permission.DELETE_PROJECT))
) -> dict:
    """Delete a project by ID."""
    project = await _get_project_or_404(id, db, user)
    await db.delete(project)
    return {"message": f"Project '{id}' deleted successfully"}
