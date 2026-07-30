from datetime import datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/projects", tags=["Projects"])

# In-memory store stub (syncs with Database models in full execution)
_projects_db_stub: dict[str, dict] = {}


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


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    organization_id: Optional[str] = Query(None, description="Filter by organization ID")
) -> List[ProjectResponse]:
    """List projects, optionally filtered by organization_id."""
    projects = list(_projects_db_stub.values())
    if organization_id:
        projects = [p for p in projects if p["organization_id"] == organization_id]
    return [ProjectResponse(**p) for p in projects]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(req: ProjectCreate) -> ProjectResponse:
    """Create a new project linked to an organization."""
    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    project_record = {
        "id": project_id,
        "name": req.name,
        "organization_id": req.organization_id,
        "description": req.description,
        "created_at": now,
    }

    _projects_db_stub[project_id] = project_record
    return ProjectResponse(**project_record)


@router.get("/{id}", response_model=ProjectResponse)
async def get_project(id: str) -> ProjectResponse:
    """Retrieve a project by ID."""
    project = _projects_db_stub.get(id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{id}' not found",
        )
    return ProjectResponse(**project)


@router.patch("/{id}", response_model=ProjectResponse)
async def update_project(id: str, req: ProjectUpdate) -> ProjectResponse:
    """Update project attributes."""
    project = _projects_db_stub.get(id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{id}' not found",
        )

    if req.name is not None:
        project["name"] = req.name
    if req.description is not None:
        project["description"] = req.description

    return ProjectResponse(**project)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_project(id: str) -> dict:
    """Delete a project by ID."""
    project = _projects_db_stub.pop(id, None)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{id}' not found",
        )
    return {"message": f"Project '{id}' deleted successfully"}
