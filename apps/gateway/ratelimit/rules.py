from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth.context import RequestAuthContext
from apps.gateway.db.models import RateLimitRule
from apps.gateway.ratelimit.limiter import RateLimiter


async def load_matching_rules(
    db: AsyncSession,
    organization_id: str | None,
    project_id: str | None,
    provider_name: str | None,
    endpoint: str,
    api_key_id: str | None = None,
) -> list[RateLimitRule]:
    """A request can be governed by several rules at once (e.g. a global default plus
    a tighter per-project override) - every enabled rule whose scope matches is
    returned, and the caller rejects the request if ANY of them is violated."""
    scope_clauses = [RateLimitRule.scope_type == "global"]
    if organization_id:
        scope_clauses.append((RateLimitRule.scope_type == "organization") & (RateLimitRule.scope_value == organization_id))
    if project_id:
        scope_clauses.append((RateLimitRule.scope_type == "project") & (RateLimitRule.scope_value == project_id))
    if provider_name:
        scope_clauses.append((RateLimitRule.scope_type == "provider") & (RateLimitRule.scope_value == provider_name))
    if api_key_id:
        scope_clauses.append((RateLimitRule.scope_type == "api_key") & (RateLimitRule.scope_value == api_key_id))
    scope_clauses.append((RateLimitRule.scope_type == "endpoint") & (RateLimitRule.scope_value == endpoint))

    query = select(RateLimitRule).where(RateLimitRule.enabled.is_(True), or_(*scope_clauses))
    result = await db.execute(query)
    return list(result.scalars().all())


async def enforce_rate_limits(
    db: AsyncSession,
    limiter: RateLimiter,
    *,
    endpoint: str,
    organization_id: str | None = None,
    project_id: str | None = None,
    provider_name: str | None = None,
    auth_context: RequestAuthContext | None = None,
) -> None:
    """Checks the API key's own per-key budget (Epic 5.3's `rate_limit_per_minute`)
    plus every configured RateLimitRule matching this request's scopes, raising 429 on
    the first violation found. Called before routing/provider calls so a rejected
    request never reaches an upstream provider."""
    if auth_context and auth_context.rate_limit_per_minute:
        result = await limiter.check("api_key", auth_context.api_key_id, auth_context.rate_limit_per_minute, 60, "sliding_window")
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="This API key has exceeded its per-key rate limit",
                headers={"Retry-After": str(int(result.retry_after_seconds) + 1)},
            )

    rules = await load_matching_rules(
        db, organization_id, project_id, provider_name, endpoint, auth_context.api_key_id if auth_context else None
    )
    for rule in rules:
        result = await limiter.check(rule.scope_type, rule.scope_value or "global", rule.limit, rule.window_seconds, rule.algorithm)
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for {rule.scope_type}" + (f" '{rule.scope_value}'" if rule.scope_value else ""),
                headers={"Retry-After": str(int(result.retry_after_seconds) + 1)},
            )
