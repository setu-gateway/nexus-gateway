import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.audit import record_audit_event
from apps.gateway.auth import DashboardUserContext, Permission, require_permission, resolve_dashboard_user_or_401
from apps.gateway.db.models import PromptTemplate, PromptTemplateVersion
from apps.gateway.db.session import get_db_session
from apps.gateway.prompts import extract_variables, render_messages
from apps.gateway.utils import fire_and_forget

router = APIRouter(prefix="/prompt-templates", tags=["Prompt Templates"])


def _audit_ctx(request: Request) -> dict:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


def _validate_messages_shape(v: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for m in v:
        if "role" not in m or "content" not in m:
            raise ValueError("each message must have 'role' and 'content'")
    return v


class PromptTemplateCreate(BaseModel):
    organization_id: str
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    messages: list[dict[str, Any]] = Field(min_length=1, description="Chat messages, may reference {{variables}}")

    @field_validator("messages")
    @classmethod
    def _validate_messages(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _validate_messages_shape(v)


class PromptTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    messages: list[dict[str, Any]] | None = Field(default=None, min_length=1)
    change_note: str | None = Field(default=None, max_length=500, description="Recorded on the new version if messages changed")

    @field_validator("messages")
    @classmethod
    def _validate_messages(cls, v: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        return _validate_messages_shape(v) if v is not None else v


class PromptTemplateResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str | None
    messages: list[dict[str, Any]]
    variables: list[str]
    current_version: int
    created_at: datetime
    updated_at: datetime


class PromptTemplateVersionResponse(BaseModel):
    id: str
    template_id: str
    version: int
    messages: list[dict[str, Any]]
    change_note: str | None
    created_at: datetime


class RenderRequest(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)


class RenderResponse(BaseModel):
    messages: list[dict[str, Any]]
    variables_used: list[str]


class RollbackRequest(BaseModel):
    version: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=500)


def _template_to_response(template: PromptTemplate) -> PromptTemplateResponse:
    return PromptTemplateResponse(
        id=str(template.id),
        organization_id=str(template.organization_id),
        name=template.name,
        description=template.description,
        messages=template.messages,
        variables=extract_variables(template.messages),
        current_version=template.current_version,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _version_to_response(v: PromptTemplateVersion) -> PromptTemplateVersionResponse:
    return PromptTemplateVersionResponse(
        id=str(v.id),
        template_id=str(v.template_id),
        version=v.version,
        messages=v.messages,
        change_note=v.change_note,
        created_at=v.created_at,
    )


async def _get_template_or_404(template_id: str, db: AsyncSession, user: DashboardUserContext) -> PromptTemplate:
    try:
        template_uuid = uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid template id: '{template_id}'") from None
    template = await db.get(PromptTemplate, template_uuid)
    if not template or not user.owns_organization(str(template.organization_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Prompt template '{template_id}' not found")
    return template


@router.post("", response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt_template(
    req: PromptTemplateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_PROMPT_TEMPLATES)),
) -> PromptTemplateResponse:
    if not user.owns_organization(req.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create a prompt template for another organization")
    template = PromptTemplate(
        id=uuid.uuid4(),
        organization_id=uuid.UUID(req.organization_id),
        name=req.name,
        description=req.description,
        messages=req.messages,
        current_version=1,
    )
    db.add(template)
    await db.flush()
    db.add(PromptTemplateVersion(id=uuid.uuid4(), template_id=template.id, version=1, messages=req.messages))
    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="prompt_template.created",
            resource_type="prompt_template",
            resource_id=str(template.id),
            organization_id=str(template.organization_id),
            details={"name": template.name},
            **_audit_ctx(request),
        )
    )
    return _template_to_response(template)


@router.get("", response_model=list[PromptTemplateResponse])
async def list_prompt_templates(
    organization_id: str = Query(description="Organization UUID to list templates for"),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[PromptTemplateResponse]:
    if not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot list prompt templates for another organization")
    result = await db.execute(
        select(PromptTemplate)
        .where(PromptTemplate.organization_id == uuid.UUID(organization_id))
        .order_by(PromptTemplate.created_at.desc())
    )
    return [_template_to_response(t) for t in result.scalars().all()]


@router.get("/{template_id}", response_model=PromptTemplateResponse)
async def get_prompt_template(
    template_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> PromptTemplateResponse:
    template = await _get_template_or_404(template_id, db, user)
    return _template_to_response(template)


@router.patch("/{template_id}", response_model=PromptTemplateResponse)
async def update_prompt_template(
    template_id: str,
    req: PromptTemplateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_PROMPT_TEMPLATES)),
) -> PromptTemplateResponse:
    """Renaming/re-describing a template edits it in place. Changing `messages` -
    the actual prompt content - instead bumps `current_version` and snapshots the new
    content as a new PromptTemplateVersion, leaving every prior version intact."""
    template = await _get_template_or_404(template_id, db, user)

    if req.name is not None:
        template.name = req.name
    if req.description is not None:
        template.description = req.description
    if req.messages is not None:
        template.messages = req.messages
        template.current_version += 1
        db.add(
            PromptTemplateVersion(
                id=uuid.uuid4(),
                template_id=template.id,
                version=template.current_version,
                messages=req.messages,
                change_note=req.change_note,
            )
        )
    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="prompt_template.updated",
            resource_type="prompt_template",
            resource_id=str(template.id),
            organization_id=str(template.organization_id),
            details={"new_version": template.current_version} if req.messages is not None else {},
            **_audit_ctx(request),
        )
    )
    return _template_to_response(template)


@router.delete("/{template_id}", status_code=status.HTTP_200_OK)
async def delete_prompt_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_PROMPT_TEMPLATES)),
) -> dict:
    template = await _get_template_or_404(template_id, db, user)
    organization_id = str(template.organization_id)
    await db.delete(template)

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="prompt_template.deleted",
            resource_type="prompt_template",
            resource_id=template_id,
            organization_id=organization_id,
            **_audit_ctx(request),
        )
    )
    return {"message": f"Prompt template '{template_id}' deleted successfully"}


@router.get("/{template_id}/versions", response_model=list[PromptTemplateVersionResponse])
async def list_prompt_template_versions(
    template_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> list[PromptTemplateVersionResponse]:
    template = await _get_template_or_404(template_id, db, user)
    result = await db.execute(
        select(PromptTemplateVersion).where(PromptTemplateVersion.template_id == template.id).order_by(PromptTemplateVersion.version.desc())
    )
    return [_version_to_response(v) for v in result.scalars().all()]


async def _get_version_or_404(template: PromptTemplate, version: int, db: AsyncSession) -> PromptTemplateVersion:
    result = await db.execute(
        select(PromptTemplateVersion).where(PromptTemplateVersion.template_id == template.id, PromptTemplateVersion.version == version)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version} not found for this template")
    return row


@router.get("/{template_id}/versions/{version}", response_model=PromptTemplateVersionResponse)
async def get_prompt_template_version(
    template_id: str,
    version: int,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> PromptTemplateVersionResponse:
    template = await _get_template_or_404(template_id, db, user)
    row = await _get_version_or_404(template, version, db)
    return _version_to_response(row)


@router.post("/{template_id}/rollback", response_model=PromptTemplateResponse)
async def rollback_prompt_template(
    template_id: str,
    req: RollbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_PROMPT_TEMPLATES)),
) -> PromptTemplateResponse:
    """Restores an older version's content as the template's current content. This
    creates a NEW version (current_version + 1) carrying that old content forward,
    rather than rewinding current_version itself - version history stays a linear,
    append-only log of what the template's content was at each point, matching how
    `git revert` (not `git reset`) treats history."""
    template = await _get_template_or_404(template_id, db, user)
    target = await _get_version_or_404(template, req.version, db)

    template.messages = target.messages
    template.current_version += 1
    db.add(
        PromptTemplateVersion(
            id=uuid.uuid4(),
            template_id=template.id,
            version=template.current_version,
            messages=target.messages,
            change_note=req.change_note or f"Rolled back to version {req.version}",
        )
    )
    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="prompt_template.rolled_back",
            resource_type="prompt_template",
            resource_id=str(template.id),
            organization_id=str(template.organization_id),
            details={"rolled_back_to": req.version, "new_version": template.current_version},
            **_audit_ctx(request),
        )
    )
    return _template_to_response(template)


@router.post("/{template_id}/render", response_model=RenderResponse)
async def render_prompt_template(
    template_id: str,
    req: RenderRequest,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> RenderResponse:
    """Substitutes {{variables}} in the template's current content, ready to send as
    the `messages` field of a /v1/chat/completions request."""
    template = await _get_template_or_404(template_id, db, user)
    rendered, missing = render_messages(template.messages, req.variables)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing value(s) for variable(s): {', '.join(missing)}",
        )
    return RenderResponse(messages=rendered, variables_used=sorted(req.variables.keys() & set(extract_variables(template.messages))))
