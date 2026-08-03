import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.db.models import RequestLog
from apps.gateway.models.catalog import ModelDefinition, ModelRegistry

# Below this, a "cheaper" candidate isn't worth surfacing - the noise of a 2% swap
# recommendation costs more in attention than it saves in tokens.
MIN_SAVINGS_PCT_TO_RECOMMEND = 10.0


@dataclass
class CostRecommendation:
    current_model: str
    current_provider: str
    current_tier: str
    recommended_model: str
    recommended_provider: str
    recommended_tier: str
    estimated_savings_pct: float
    projected_savings_usd: float
    based_on_requests: int
    trade_off: str


def _trade_off_note(current: ModelDefinition, candidate: ModelDefinition) -> str:
    notes: list[str] = []
    if candidate.tier != current.tier:
        notes.append(f"moves from '{current.tier}' tier to '{candidate.tier}' tier")
    if candidate.context_window < current.context_window:
        notes.append(f"smaller context window ({candidate.context_window:,} vs {current.context_window:,} tokens)")
    if current.supports_vision and not candidate.supports_vision:
        notes.append("loses vision/multimodal support")
    if current.supports_tools and not candidate.supports_tools:
        notes.append("loses tool/function-calling support")
    if not notes:
        return "same tier and capabilities - a straightforward switch with no trade-off"
    return "; ".join(notes)


def _best_cheaper_candidate(
    current: ModelDefinition, avg_prompt_tokens: float, avg_completion_tokens: float, model_registry: ModelRegistry
) -> tuple[ModelDefinition, float] | None:
    """Cheapest chat model (any provider, any tier) other than `current`, using the
    *actual* observed prompt/completion token split for this workload rather than a
    generic assumption - a model that's cheaper per input token but pricier per output
    token can rank differently depending on how verbose real responses are."""
    best: tuple[ModelDefinition, float] | None = None
    for candidate in model_registry.list_models():
        if candidate.model_id == current.model_id or candidate.supports_embeddings != current.supports_embeddings:
            continue
        projected_cost = candidate.estimate_cost(avg_prompt_tokens, avg_completion_tokens)
        if best is None or projected_cost < best[1]:
            best = (candidate, projected_cost)
    return best


async def generate_cost_recommendations(
    db: AsyncSession,
    organization_id: str,
    model_registry: ModelRegistry,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[CostRecommendation]:
    """Analyze actual usage (request_logs) for an organization and recommend cheaper
    equivalent models where the historical workload shows a real, material savings
    opportunity - not a theoretical price-list comparison. Chat/completion models
    only; embeddings pricing dynamics are different enough to warrant a separate
    comparison this doesn't attempt."""
    query = select(
        RequestLog.requested_model,
        func.count(RequestLog.id),
        func.avg(RequestLog.prompt_tokens),
        func.avg(RequestLog.completion_tokens),
        func.sum(RequestLog.estimated_cost),
    ).where(RequestLog.organization_id == uuid.UUID(organization_id), RequestLog.status == "success")
    if since:
        query = query.where(RequestLog.created_at >= since)
    if until:
        query = query.where(RequestLog.created_at <= until)
    query = query.group_by(RequestLog.requested_model)

    rows = (await db.execute(query)).all()

    recommendations: list[CostRecommendation] = []
    for requested_model, count, avg_prompt, avg_completion, total_cost in rows:
        current = model_registry.get_model(requested_model)
        if current is None or current.supports_embeddings or not total_cost or count == 0:
            continue

        avg_prompt_tokens = avg_prompt or 0.0
        avg_completion_tokens = avg_completion or 0.0
        best = _best_cheaper_candidate(current, avg_prompt_tokens, avg_completion_tokens, model_registry)
        if best is None:
            continue
        candidate, projected_cost_per_request = best

        projected_total_cost = projected_cost_per_request * count
        if projected_total_cost >= total_cost:
            continue

        savings_pct = ((total_cost - projected_total_cost) / total_cost) * 100
        if savings_pct < MIN_SAVINGS_PCT_TO_RECOMMEND:
            continue

        recommendations.append(
            CostRecommendation(
                current_model=current.model_id,
                current_provider=current.provider_name,
                current_tier=current.tier,
                recommended_model=candidate.model_id,
                recommended_provider=candidate.provider_name,
                recommended_tier=candidate.tier,
                estimated_savings_pct=round(savings_pct, 1),
                projected_savings_usd=round(total_cost - projected_total_cost, 6),
                based_on_requests=count,
                trade_off=_trade_off_note(current, candidate),
            )
        )

    recommendations.sort(key=lambda r: r.projected_savings_usd, reverse=True)
    return recommendations
