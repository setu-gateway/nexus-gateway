import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.audit import record_audit_event
from apps.gateway.auth import DashboardUserContext, Permission, require_permission, resolve_dashboard_user_or_401
from apps.gateway.db.models import RoutingRule
from apps.gateway.db.session import get_db_session
from apps.gateway.routing.rules import RuleActionType, RuleConditionError, parse_condition
from apps.gateway.utils import fire_and_forget

router = APIRouter(prefix="/routing-rules", tags=["Routing Rules"])


def _audit_ctx(request: Request) -> dict:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


class RoutingRuleCreate(BaseModel):
    organization_id: str
    name: str = Field(min_length=1, max_length=255)
    condition_expression: str = Field(description="e.g. 'latency > 500ms', 'provider == unavailable'")
    action_type: RuleActionType
    action_provider: str | None = Field(default=None, description="Required for 'fallback'/'use' actions")
    priority: int = Field(default=100, description="Lower runs first")
    enabled: bool = True


class RoutingRuleUpdate(BaseModel):
    name: str | None = None
    condition_expression: str | None = None
    action_type: RuleActionType | None = None
    action_provider: str | None = None
    priority: int | None = None
    enabled: bool | None = None


class RoutingRuleResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    condition_expression: str
    action_type: str
    action_provider: str | None
    priority: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


def _to_response(rule: RoutingRule) -> RoutingRuleResponse:
    return RoutingRuleResponse(
        id=str(rule.id),
        organization_id=str(rule.organization_id),
        name=rule.name,
        condition_expression=rule.condition_expression,
        action_type=rule.action_type,
        action_provider=rule.action_provider,
        priority=rule.priority,
        enabled=rule.enabled,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _validate_condition(expression: str) -> None:
    try:
        parse_condition(expression)
    except RuleConditionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("", response_model=RoutingRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_routing_rule(
    req: RoutingRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_ROUTING)),
) -> RoutingRuleResponse:
    """Create an organization routing rule. The condition is validated eagerly so a
    typo is rejected at creation time rather than silently skipped during routing."""
    if not user.owns_organization(req.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create a routing rule for another organization")
    _validate_condition(req.condition_expression)
    if req.action_type in (RuleActionType.FALLBACK, RuleActionType.USE) and not req.action_provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"action_provider is required for action_type '{req.action_type.value}'",
        )

    rule = RoutingRule(
        id=uuid.uuid4(),
        organization_id=uuid.UUID(req.organization_id),
        name=req.name,
        condition_expression=req.condition_expression,
        action_type=req.action_type.value,
        action_provider=req.action_provider,
        priority=req.priority,
        enabled=req.enabled,
    )
    db.add(rule)
    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="routing_rule.created",
            resource_type="routing_rule",
            resource_id=str(rule.id),
            organization_id=str(rule.organization_id),
            details={"name": rule.name, "condition_expression": rule.condition_expression},
            **_audit_ctx(request),
        )
    )

    return _to_response(rule)


@router.get("", response_model=list[RoutingRuleResponse])
async def list_routing_rules(
    organization_id: str = Query(description="Organization UUID to list rules for"),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[RoutingRuleResponse]:
    if not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot list routing rules for another organization")
    result = await db.execute(
        select(RoutingRule).where(RoutingRule.organization_id == uuid.UUID(organization_id)).order_by(RoutingRule.priority)
    )
    return [_to_response(r) for r in result.scalars().all()]


async def _get_rule_or_404(rule_id: str, db: AsyncSession, user: DashboardUserContext) -> RoutingRule:
    result = await db.execute(select(RoutingRule).where(RoutingRule.id == uuid.UUID(rule_id)))
    rule = result.scalar_one_or_none()
    if not rule or not user.owns_organization(str(rule.organization_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Routing rule '{rule_id}' not found")
    return rule


@router.get("/{rule_id}", response_model=RoutingRuleResponse)
async def get_routing_rule(
    rule_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> RoutingRuleResponse:
    rule = await _get_rule_or_404(rule_id, db, user)
    return _to_response(rule)


@router.patch("/{rule_id}", response_model=RoutingRuleResponse)
async def update_routing_rule(
    rule_id: str,
    req: RoutingRuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_ROUTING)),
) -> RoutingRuleResponse:
    rule = await _get_rule_or_404(rule_id, db, user)

    if req.condition_expression is not None:
        _validate_condition(req.condition_expression)
        rule.condition_expression = req.condition_expression
    if req.name is not None:
        rule.name = req.name
    if req.action_type is not None:
        rule.action_type = req.action_type.value
    if req.action_provider is not None:
        rule.action_provider = req.action_provider
    if req.priority is not None:
        rule.priority = req.priority
    if req.enabled is not None:
        rule.enabled = req.enabled

    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="routing_rule.updated",
            resource_type="routing_rule",
            resource_id=str(rule.id),
            organization_id=str(rule.organization_id),
            details=req.model_dump(exclude_none=True, mode="json"),
            **_audit_ctx(request),
        )
    )

    return _to_response(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_200_OK)
async def delete_routing_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_ROUTING)),
) -> dict:
    rule = await _get_rule_or_404(rule_id, db, user)
    organization_id = str(rule.organization_id)
    await db.delete(rule)

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="routing_rule.deleted",
            resource_type="routing_rule",
            resource_id=rule_id,
            organization_id=organization_id,
            **_audit_ctx(request),
        )
    )

    return {"message": f"Routing rule '{rule_id}' deleted successfully"}
