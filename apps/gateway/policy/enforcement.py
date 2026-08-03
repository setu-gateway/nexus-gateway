import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.db.models import Policy
from apps.gateway.models.catalog import ModelRegistry
from apps.gateway.policy.secrets import find_secrets_in_messages


class PolicyViolation(Exception):
    """Raised when a request fails an enabled organization policy. Callers turn this
    into an HTTP 403 - distinct from routing failures (503, no provider available),
    since this is the request being refused outright rather than unroutable."""

    def __init__(self, policy_name: str, reason: str):
        self.policy_name = policy_name
        self.reason = reason
        super().__init__(f"Blocked by policy '{policy_name}': {reason}")


def _check_provider_allowlist(policy: Policy, provider_name: str) -> str | None:
    allowed = policy.config.get("providers", [])
    if provider_name not in allowed:
        return f"provider '{provider_name}' is not in the allowed list ({', '.join(allowed) or 'none'})"
    return None


def _check_provider_denylist(policy: Policy, provider_name: str) -> str | None:
    denied = policy.config.get("providers", [])
    if provider_name in denied:
        return f"provider '{provider_name}' is on the denied list"
    return None


def _check_min_context_window(policy: Policy, context_window: int) -> str | None:
    minimum = policy.config.get("min_context_window", 0)
    if context_window < minimum:
        return f"model's context window ({context_window}) is below the required minimum ({minimum})"
    return None


def _check_block_secrets(messages: list[dict[str, Any]]) -> str | None:
    matches = find_secrets_in_messages(messages)
    if matches:
        labels = sorted({m.label for m in matches})
        return f"prompt appears to contain a secret ({', '.join(labels)})"
    return None


async def enforce_policies(
    db: AsyncSession,
    organization_id: str,
    requested_model: str,
    messages: list[dict[str, Any]],
    model_registry: ModelRegistry,
) -> None:
    """Evaluate every enabled policy for `organization_id` against this request,
    raising PolicyViolation on the first one it fails. All enabled policies must
    pass (AND semantics) - each is an independent guardrail, not alternatives to
    choose between. Anonymous requests (no organization_id) have no policies to
    enforce and always pass through unchanged."""
    result = await db.execute(select(Policy).where(Policy.organization_id == uuid.UUID(organization_id), Policy.enabled.is_(True)))
    policies = result.scalars().all()
    if not policies:
        return

    model_def = model_registry.get_model(requested_model)

    for policy in policies:
        violation: str | None = None

        if policy.policy_type == "block_secrets":
            violation = _check_block_secrets(messages)
        elif policy.policy_type == "min_context_window" and model_def is not None:
            violation = _check_min_context_window(policy, model_def.context_window)
        elif policy.policy_type == "provider_allowlist" and model_def is not None:
            violation = _check_provider_allowlist(policy, model_def.provider_name)
        elif policy.policy_type == "provider_denylist" and model_def is not None:
            violation = _check_provider_denylist(policy, model_def.provider_name)

        if violation:
            raise PolicyViolation(policy_name=policy.name, reason=violation)
