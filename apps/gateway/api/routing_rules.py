from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.db.models import RoutingRule
from apps.gateway.db.session import get_db_session
from apps.gateway.routing.rules import RuleActionType, RuleConditionError, parse_condition

router = APIRouter(prefix="/routing-rules", tags=["Routing Rules"])


class RoutingRuleCreate(BaseModel):
    organization_id: str
    name: str = Field(min_length=1, max_length=255)
    condition_expression: str = Field(description="e.g. 'latency > 500ms', 'provider == unavailable'")
    action_type: RuleActionType
    action_provider: Optional[str] = Field(default=None, description="Required for 'fallback'/'use' actions")
    priority: int = Field(default=100, description="Lower runs first")
    enabled: bool = True


class RoutingRuleUpdate(BaseModel):
    name: Optional[str] = None
    condition_expression: Optional[str] = None
    action_type: Optional[RuleActionType] = None
    action_provider: Optional[str] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None


class RoutingRuleResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    condition_expression: str
    action_type: str
    action_provider: Optional[str]
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("", response_model=RoutingRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_routing_rule(
    req: RoutingRuleCreate, db: AsyncSession = Depends(get_db_session)
) -> RoutingRuleResponse:
    """Create an organization routing rule. The condition is validated eagerly so a
    typo is rejected at creation time rather than silently skipped during routing."""
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
    return _to_response(rule)


@router.get("", response_model=List[RoutingRuleResponse])
async def list_routing_rules(
    organization_id: str = Query(description="Organization UUID to list rules for"),
    db: AsyncSession = Depends(get_db_session),
) -> List[RoutingRuleResponse]:
    result = await db.execute(
        select(RoutingRule)
        .where(RoutingRule.organization_id == uuid.UUID(organization_id))
        .order_by(RoutingRule.priority)
    )
    return [_to_response(r) for r in result.scalars().all()]


async def _get_rule_or_404(rule_id: str, db: AsyncSession) -> RoutingRule:
    result = await db.execute(select(RoutingRule).where(RoutingRule.id == uuid.UUID(rule_id)))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Routing rule '{rule_id}' not found")
    return rule


@router.get("/{rule_id}", response_model=RoutingRuleResponse)
async def get_routing_rule(rule_id: str, db: AsyncSession = Depends(get_db_session)) -> RoutingRuleResponse:
    rule = await _get_rule_or_404(rule_id, db)
    return _to_response(rule)


@router.patch("/{rule_id}", response_model=RoutingRuleResponse)
async def update_routing_rule(
    rule_id: str, req: RoutingRuleUpdate, db: AsyncSession = Depends(get_db_session)
) -> RoutingRuleResponse:
    rule = await _get_rule_or_404(rule_id, db)

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
    return _to_response(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_200_OK)
async def delete_routing_rule(rule_id: str, db: AsyncSession = Depends(get_db_session)) -> dict:
    rule = await _get_rule_or_404(rule_id, db)
    await db.delete(rule)
    return {"message": f"Routing rule '{rule_id}' deleted successfully"}
