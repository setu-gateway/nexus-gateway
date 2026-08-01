from enum import Enum
from typing import Any, List, Optional
import re

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.logging.logger import get_logger

logger = get_logger("routing_rules")


class RuleActionType(str, Enum):
    FALLBACK = "fallback"
    USE = "use"
    REJECT = "reject"


class RuleConditionError(ValueError):
    """Raised when a rule's condition_expression can't be parsed."""


class ParsedCondition(BaseModel):
    field: str
    operator: str
    value: Any


class RuleSpec(BaseModel):
    """Pure, DB-independent representation of one org routing rule - keeps the
    parsing/evaluation logic in this module unit-testable without a database."""

    name: str
    condition_expression: str
    action_type: RuleActionType
    action_provider: Optional[str] = None
    priority: int = 100
    enabled: bool = True


class RuleOutcome(BaseModel):
    matched: bool
    rule_name: Optional[str] = None
    action_type: Optional[RuleActionType] = None
    action_provider: Optional[str] = None


_CONDITION_PATTERN = re.compile(r"^\s*(?P<field>[a-zA-Z_]+)\s*(?P<operator>==|!=|>=|<=|>|<)\s*(?P<value>.+?)\s*$")
_LATENCY_FIELDS = {"latency", "latency_ms"}
_COST_FIELDS = {"estimated_cost", "cost"}
_STATUS_FIELDS = {"provider", "provider_status", "status"}


def _parse_numeric(raw_value: str) -> float:
    cleaned = raw_value.strip().lower()
    if cleaned.endswith("ms"):
        return float(cleaned[:-2])
    if cleaned.endswith("s"):
        return float(cleaned[:-1]) * 1000.0  # normalize seconds -> ms
    if cleaned.endswith("%"):
        return float(cleaned[:-1])
    return float(cleaned)


def parse_condition(expression: str) -> ParsedCondition:
    """Parse a compact condition like 'latency > 500ms' or 'provider == unavailable'
    into a structured (field, operator, value).

    Deliberately NOT an eval()-based expression language: the grammar is a single fixed
    regex and the field name is checked against a whitelist, so a malformed or malicious
    org-authored rule can never execute arbitrary code - it just fails to parse.
    """
    match = _CONDITION_PATTERN.match(expression)
    if not match:
        raise RuleConditionError(f"Unrecognized rule condition syntax: '{expression}'")

    field = match.group("field").lower()
    operator = match.group("operator")
    raw_value = match.group("value").strip()

    if field in _LATENCY_FIELDS or field in _COST_FIELDS:
        return ParsedCondition(
            field="latency_ms" if field in _LATENCY_FIELDS else "estimated_cost",
            operator=operator,
            value=_parse_numeric(raw_value),
        )

    if field in _STATUS_FIELDS:
        return ParsedCondition(field="provider_status", operator=operator, value=raw_value.strip("\"'").lower())

    raise RuleConditionError(f"Unknown rule field '{field}'. Supported fields: latency, estimated_cost, provider")


def _condition_matches(condition: ParsedCondition, context: dict) -> bool:
    actual = context.get(condition.field)
    if actual is None:
        return False

    if condition.field == "provider_status":
        actual_s, expected_s = str(actual).lower(), str(condition.value).lower()
        if condition.operator == "==":
            return actual_s == expected_s
        if condition.operator == "!=":
            return actual_s != expected_s
        return False

    try:
        actual_num, expected_num = float(actual), float(condition.value)
    except (TypeError, ValueError):
        return False

    return {
        ">": actual_num > expected_num,
        "<": actual_num < expected_num,
        ">=": actual_num >= expected_num,
        "<=": actual_num <= expected_num,
        "==": actual_num == expected_num,
        "!=": actual_num != expected_num,
    }.get(condition.operator, False)


def evaluate_rules(rules: List[RuleSpec], context: dict) -> RuleOutcome:
    """Evaluate rules in priority order (lowest number first) against a request
    context, returning the first match. `context` keys: latency_ms, estimated_cost,
    provider_status ('available' | 'unavailable')."""
    for rule in sorted((r for r in rules if r.enabled), key=lambda r: r.priority):
        try:
            condition = parse_condition(rule.condition_expression)
        except RuleConditionError:
            logger.warning(f"Skipping unparseable routing rule '{rule.name}': {rule.condition_expression}")
            continue

        if _condition_matches(condition, context):
            return RuleOutcome(
                matched=True,
                rule_name=rule.name,
                action_type=rule.action_type,
                action_provider=rule.action_provider,
            )
    return RuleOutcome(matched=False)


async def load_org_rules(db: AsyncSession, organization_id: Any) -> List[RuleSpec]:
    """Fetch an organization's enabled routing rules from the database as RuleSpecs."""
    from apps.gateway.db.models import RoutingRule  # local import avoids a routing<->db cycle at module load

    result = await db.execute(
        select(RoutingRule).where(RoutingRule.organization_id == organization_id, RoutingRule.enabled.is_(True))
    )
    rows = result.scalars().all()
    return [
        RuleSpec(
            name=row.name,
            condition_expression=row.condition_expression,
            action_type=RuleActionType(row.action_type),
            action_provider=row.action_provider,
            priority=row.priority,
            enabled=row.enabled,
        )
        for row in rows
    ]
