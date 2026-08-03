from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth import DashboardUserContext, resolve_dashboard_user_or_401
from apps.gateway.db.session import get_db_session
from apps.gateway.optimizer import generate_cost_recommendations
from apps.gateway.providers.instance import model_registry

router = APIRouter(prefix="/optimizer", tags=["AI Cost Optimizer"])


class CostRecommendationResponse(BaseModel):
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


@router.get("/recommendations", response_model=list[CostRecommendationResponse])
async def get_cost_recommendations(
    organization_id: str = Query(description="Organization UUID to analyze usage for"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[CostRecommendationResponse]:
    """Cheaper-model recommendations based on this organization's *actual* recorded
    usage (request_logs), not a generic price list - see
    apps/gateway/optimizer/recommendations.py for the methodology and the trade-offs
    each recommendation calls out."""
    if not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view cost recommendations for another organization")

    recommendations = await generate_cost_recommendations(db, organization_id, model_registry, since=since, until=until)
    return [CostRecommendationResponse(**vars(r)) for r in recommendations]
