import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.audit import record_audit_event
from apps.gateway.auth import DashboardUserContext, Permission, require_permission, resolve_dashboard_user_or_401
from apps.gateway.db.models import Policy
from apps.gateway.db.session import get_db_session
from apps.gateway.utils import fire_and_forget

router = APIRouter(prefix="/policies", tags=["Enterprise Policy Engine"])

VALID_POLICY_TYPES = {"provider_allowlist", "provider_denylist", "min_context_window", "block_secrets"}


def _audit_ctx(request: Request) -> dict:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


def _validate_config(policy_type: str, config: dict[str, Any]) -> None:
    if policy_type in ("provider_allowlist", "provider_denylist"):
        providers = config.get("providers")
        if not isinstance(providers, list) or not providers or not all(isinstance(p, str) for p in providers):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{policy_type}' requires config.providers to be a non-empty list of provider names",
            )
    elif policy_type == "min_context_window":
        minimum = config.get("min_context_window")
        if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="'min_context_window' requires config.min_context_window to be a positive integer",
            )
    # block_secrets takes no config - its pattern set is fixed (apps/gateway/policy/secrets.py).


class PolicyCreate(BaseModel):
    organization_id: str
    name: str = Field(min_length=1, max_length=255)
    policy_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("policy_type")
    @classmethod
    def validate_policy_type(cls, v: str) -> str:
        if v not in VALID_POLICY_TYPES:
            raise ValueError(f"policy_type must be one of {sorted(VALID_POLICY_TYPES)}")
        return v


class PolicyUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class PolicyResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    policy_type: str
    config: dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime


def _to_response(policy: Policy) -> PolicyResponse:
    return PolicyResponse(
        id=str(policy.id),
        organization_id=str(policy.organization_id),
        name=policy.name,
        policy_type=policy.policy_type,
        config=policy.config,
        enabled=policy.enabled,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


@router.post("", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    req: PolicyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_POLICIES)),
) -> PolicyResponse:
    """Create an organization-wide guardrail. Config shape is validated eagerly per
    policy_type so a malformed policy can never silently no-op during enforcement."""
    if not user.owns_organization(req.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create a policy for another organization")
    _validate_config(req.policy_type, req.config)

    policy = Policy(
        id=uuid.uuid4(),
        organization_id=uuid.UUID(req.organization_id),
        name=req.name,
        policy_type=req.policy_type,
        config=req.config,
        enabled=req.enabled,
    )
    db.add(policy)
    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="policy.created",
            resource_type="policy",
            resource_id=str(policy.id),
            organization_id=str(policy.organization_id),
            details={"name": policy.name, "policy_type": policy.policy_type},
            **_audit_ctx(request),
        )
    )

    return _to_response(policy)


@router.get("", response_model=list[PolicyResponse])
async def list_policies(
    organization_id: str = Query(description="Organization UUID to list policies for"),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[PolicyResponse]:
    if not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot list policies for another organization")
    result = await db.execute(select(Policy).where(Policy.organization_id == uuid.UUID(organization_id)).order_by(Policy.created_at))
    return [_to_response(p) for p in result.scalars().all()]


async def _get_policy_or_404(policy_id: str, db: AsyncSession, user: DashboardUserContext) -> Policy:
    result = await db.execute(select(Policy).where(Policy.id == uuid.UUID(policy_id)))
    policy = result.scalar_one_or_none()
    if not policy or not user.owns_organization(str(policy.organization_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Policy '{policy_id}' not found")
    return policy


@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> PolicyResponse:
    policy = await _get_policy_or_404(policy_id, db, user)
    return _to_response(policy)


@router.patch("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: str,
    req: PolicyUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_POLICIES)),
) -> PolicyResponse:
    policy = await _get_policy_or_404(policy_id, db, user)

    if req.config is not None:
        _validate_config(policy.policy_type, req.config)
        policy.config = req.config
    if req.name is not None:
        policy.name = req.name
    if req.enabled is not None:
        policy.enabled = req.enabled

    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="policy.updated",
            resource_type="policy",
            resource_id=str(policy.id),
            organization_id=str(policy.organization_id),
            details=req.model_dump(exclude_none=True, mode="json"),
            **_audit_ctx(request),
        )
    )

    return _to_response(policy)


@router.delete("/{policy_id}", status_code=status.HTTP_200_OK)
async def delete_policy(
    policy_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_POLICIES)),
) -> dict:
    policy = await _get_policy_or_404(policy_id, db, user)
    organization_id = str(policy.organization_id)
    await db.delete(policy)

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="policy.deleted",
            resource_type="policy",
            resource_id=policy_id,
            organization_id=organization_id,
            **_audit_ctx(request),
        )
    )

    return {"message": f"Policy '{policy_id}' deleted successfully"}
