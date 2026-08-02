import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth import DashboardUserContext, Role, require_role, resolve_dashboard_user_or_401
from apps.gateway.db.models import RateLimitRule
from apps.gateway.db.session import get_db_session

router = APIRouter(prefix="/rate-limits", tags=["Rate Limits"])

VALID_SCOPE_TYPES = {"global", "organization", "project", "api_key", "provider", "endpoint"}
VALID_ALGORITHMS = {"fixed_window", "sliding_window", "token_bucket"}


class RateLimitRuleCreateRequest(BaseModel):
    scope_type: str = Field(description="One of: global, organization, project, api_key, provider, endpoint")
    scope_value: str | None = Field(default=None, description="Identifier within scope_type; omit only for 'global'")
    algorithm: str = Field(default="sliding_window", description="fixed_window, sliding_window, or token_bucket")
    limit: int = Field(gt=0, description="Max requests allowed per window")
    window_seconds: int = Field(default=60, gt=0, description="Window size in seconds")
    enabled: bool = Field(default=True)

    @field_validator("scope_type")
    @classmethod
    def _validate_scope_type(cls, v: str) -> str:
        if v not in VALID_SCOPE_TYPES:
            raise ValueError(f"scope_type must be one of {sorted(VALID_SCOPE_TYPES)}")
        return v

    @field_validator("algorithm")
    @classmethod
    def _validate_algorithm(cls, v: str) -> str:
        if v not in VALID_ALGORITHMS:
            raise ValueError(f"algorithm must be one of {sorted(VALID_ALGORITHMS)}")
        return v


class RateLimitRuleUpdateRequest(BaseModel):
    algorithm: str | None = None
    limit: int | None = Field(default=None, gt=0)
    window_seconds: int | None = Field(default=None, gt=0)
    enabled: bool | None = None

    @field_validator("algorithm")
    @classmethod
    def _validate_algorithm(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_ALGORITHMS:
            raise ValueError(f"algorithm must be one of {sorted(VALID_ALGORITHMS)}")
        return v


class RateLimitRuleResponse(BaseModel):
    id: str
    scope_type: str
    scope_value: str | None
    algorithm: str
    limit: int
    window_seconds: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


def _to_response(rule: RateLimitRule) -> RateLimitRuleResponse:
    return RateLimitRuleResponse(
        id=str(rule.id),
        scope_type=rule.scope_type,
        scope_value=rule.scope_value,
        algorithm=rule.algorithm,
        limit=rule.limit,
        window_seconds=rule.window_seconds,
        enabled=rule.enabled,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


async def _get_rule_or_404(id: str, db: AsyncSession) -> RateLimitRule:
    try:
        rule_id = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Rate limit rule '{id}' not found") from None
    result = await db.execute(select(RateLimitRule).where(RateLimitRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Rate limit rule '{id}' not found")
    return rule


@router.post("", response_model=RateLimitRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rate_limit_rule(
    req: RateLimitRuleCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    _user: DashboardUserContext = Depends(require_role(Role.ADMIN)),
) -> RateLimitRuleResponse:
    """Rate limit rules are platform config, not a tenant-scoped resource - scope_value
    is a free-form identifier (an org/project/key id when scope_type calls for one),
    not a foreign key, so this can't enforce organization ownership the way the
    tenant-scoped routers do. Role.ADMIN is the bar for touching shared platform
    config; a genuinely fine-grained per-organization check isn't possible with
    today's schema."""
    if req.scope_type != "global" and not req.scope_value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="scope_value is required unless scope_type is 'global'")

    rule = RateLimitRule(
        id=uuid.uuid4(),
        scope_type=req.scope_type,
        scope_value=req.scope_value,
        algorithm=req.algorithm,
        limit=req.limit,
        window_seconds=req.window_seconds,
        enabled=req.enabled,
    )
    db.add(rule)
    await db.flush()
    return _to_response(rule)


@router.get("", response_model=list[RateLimitRuleResponse])
async def list_rate_limit_rules(
    scope_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    _user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[RateLimitRuleResponse]:
    query = select(RateLimitRule)
    if scope_type:
        query = query.where(RateLimitRule.scope_type == scope_type)
    result = await db.execute(query.order_by(RateLimitRule.created_at.desc()))
    return [_to_response(r) for r in result.scalars().all()]


@router.get("/{id}", response_model=RateLimitRuleResponse)
async def get_rate_limit_rule(
    id: str, db: AsyncSession = Depends(get_db_session), _user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> RateLimitRuleResponse:
    return _to_response(await _get_rule_or_404(id, db))


@router.patch("/{id}", response_model=RateLimitRuleResponse)
async def update_rate_limit_rule(
    id: str,
    req: RateLimitRuleUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    _user: DashboardUserContext = Depends(require_role(Role.ADMIN)),
) -> RateLimitRuleResponse:
    rule = await _get_rule_or_404(id, db)
    if req.algorithm is not None:
        rule.algorithm = req.algorithm
    if req.limit is not None:
        rule.limit = req.limit
    if req.window_seconds is not None:
        rule.window_seconds = req.window_seconds
    if req.enabled is not None:
        rule.enabled = req.enabled
    await db.flush()
    return _to_response(rule)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_rate_limit_rule(
    id: str, db: AsyncSession = Depends(get_db_session), _user: DashboardUserContext = Depends(require_role(Role.ADMIN))
) -> dict:
    rule = await _get_rule_or_404(id, db)
    await db.delete(rule)
    await db.flush()
    return {"message": f"Rate limit rule '{id}' deleted successfully"}
