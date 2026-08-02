import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth import DashboardUserContext, resolve_dashboard_user_or_401
from apps.gateway.db.models import RequestLog
from apps.gateway.db.session import get_db_session
from apps.gateway.providers.instance import provider_registry, routing_engine
from apps.gateway.routing import (
    NoHealthyProviderError,
    ReplayResult,
    RoutingPolicy,
    SimulationOutcome,
    default_simulation_sample,
    replay_request,
    simulate_policy,
)

router = APIRouter(prefix="/routing", tags=["Routing Tools"])


class SimulationRequest(BaseModel):
    policy: RoutingPolicy
    models: list[str] | None = None
    sample_size: int = 50
    organization_id: str | None = None
    trials_per_model: int = 1


@router.post("/simulate", response_model=SimulationOutcome)
async def simulate_routing_policy(
    req: SimulationRequest,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> SimulationOutcome:
    """Policy Simulator: preview a routing policy's effect on provider distribution
    before enabling it - never touches production traffic or the live router's state
    (see apps/gateway/routing/simulator.py)."""
    if req.organization_id and not user.owns_organization(req.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot simulate using another organization's traffic")

    models = req.models
    if not models:
        # Always scoped to the caller's own organization's traffic - sampling recent
        # models across every tenant would leak what other organizations are using.
        recent: list[str] = []
        if user.organization_id:
            query = (
                select(RequestLog.requested_model)
                .where(RequestLog.organization_id == uuid.UUID(user.organization_id))
                .order_by(RequestLog.created_at.desc())
                .limit(req.sample_size)
            )
            recent = [row[0] for row in (await db.execute(query)).all()]
        models = default_simulation_sample(routing_engine, recent_models=recent or None)

    if not models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No models to simulate: pass 'models' explicitly or record some traffic first",
        )

    return simulate_policy(routing_engine, req.policy, models, trials_per_model=req.trials_per_model)


class ReplayRequestBody(BaseModel):
    messages: list[dict[str, Any]] = Field(description="Same shape as /v1/chat/completions messages")
    model: str | None = Field(default=None, description="Resolve candidate providers from this model's catalog entry + equivalents")
    providers: list[str] | None = Field(default=None, description="Explicit provider list, overriding model-based resolution")
    temperature: float | None = 0.7
    top_p: float | None = 1.0
    max_tokens: int | None = None


class ReplayResponse(BaseModel):
    results: list[ReplayResult]


@router.post("/replay", response_model=ReplayResponse)
async def replay_chat_request(
    req: ReplayRequestBody, _user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> ReplayResponse:
    """Request Replay: run the same messages against multiple providers concurrently
    for testing, regression analysis, or side-by-side comparison. Not recorded to
    analytics - this is a diagnostic tool, not production traffic."""
    if not req.messages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Field 'messages' is required")

    if req.providers:
        candidates = [(p.lower(), req.model or p.lower()) for p in req.providers]
    elif req.model:
        try:
            decision = routing_engine.route(req.model)
        except NoHealthyProviderError as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
        candidates = [(c.provider_name, c.upstream_model) for c in decision.candidates]
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide either 'model' or an explicit 'providers' list")

    results = await replay_request(
        provider_registry,
        candidates,
        req.messages,
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
    )
    return ReplayResponse(results=results)
