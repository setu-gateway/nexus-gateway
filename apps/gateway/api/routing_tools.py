from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    models: Optional[List[str]] = None
    sample_size: int = 50
    organization_id: Optional[str] = None
    trials_per_model: int = 1


@router.post("/simulate", response_model=SimulationOutcome)
async def simulate_routing_policy(
    req: SimulationRequest, db: AsyncSession = Depends(get_db_session)
) -> SimulationOutcome:
    """Policy Simulator: preview a routing policy's effect on provider distribution
    before enabling it - never touches production traffic or the live router's state
    (see apps/gateway/routing/simulator.py)."""
    models = req.models
    if not models:
        query = select(RequestLog.requested_model).order_by(RequestLog.created_at.desc()).limit(req.sample_size)
        if req.organization_id:
            query = query.where(RequestLog.organization_id == uuid.UUID(req.organization_id))
        recent = [row[0] for row in (await db.execute(query)).all()]
        models = default_simulation_sample(routing_engine, recent_models=recent or None)

    if not models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No models to simulate: pass 'models' explicitly or record some traffic first",
        )

    return simulate_policy(routing_engine, req.policy, models, trials_per_model=req.trials_per_model)


class ReplayRequestBody(BaseModel):
    messages: List[Dict[str, Any]] = Field(description="Same shape as /v1/chat/completions messages")
    model: Optional[str] = Field(
        default=None, description="Resolve candidate providers from this model's catalog entry + equivalents"
    )
    providers: Optional[List[str]] = Field(
        default=None, description="Explicit provider list, overriding model-based resolution"
    )
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    max_tokens: Optional[int] = None


class ReplayResponse(BaseModel):
    results: List[ReplayResult]


@router.post("/replay", response_model=ReplayResponse)
async def replay_chat_request(req: ReplayRequestBody) -> ReplayResponse:
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
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
        candidates = [(c.provider_name, c.upstream_model) for c in decision.candidates]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Provide either 'model' or an explicit 'providers' list"
        )

    results = await replay_request(
        provider_registry,
        candidates,
        req.messages,
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
    )
    return ReplayResponse(results=results)
