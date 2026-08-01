from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.db.models import RequestLog
from apps.gateway.db.session import get_db_session

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class RequestLogResponse(BaseModel):
    id: str
    request_id: str
    organization_id: Optional[str]
    requested_model: str
    selected_provider: Optional[str]
    routing_policy: Optional[str]
    fallback_used: bool
    rule_applied: Optional[str]
    status: str
    error_message: Optional[str]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    estimated_cost: float
    cache_hit: bool
    latency_ms: float
    timeline: Optional[Dict[str, Any]]
    created_at: datetime


class ProviderBreakdown(BaseModel):
    provider: str
    requests: int
    errors: int
    avg_latency_ms: float
    total_cost: float


class AnalyticsSummary(BaseModel):
    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate: float
    avg_latency_ms: float
    total_estimated_cost: float
    total_tokens: int
    cache_hit_rate: float
    fallback_rate: float
    by_provider: List[ProviderBreakdown]


def _to_response(row: RequestLog) -> RequestLogResponse:
    return RequestLogResponse(
        id=str(row.id),
        request_id=row.request_id,
        organization_id=str(row.organization_id) if row.organization_id else None,
        requested_model=row.requested_model,
        selected_provider=row.selected_provider,
        routing_policy=row.routing_policy,
        fallback_used=row.fallback_used,
        rule_applied=row.rule_applied,
        status=row.status,
        error_message=row.error_message,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens,
        estimated_cost=row.estimated_cost,
        cache_hit=row.cache_hit,
        latency_ms=row.latency_ms,
        timeline=row.timeline,
        created_at=row.created_at,
    )


@router.get("/requests", response_model=List[RequestLogResponse])
async def list_request_logs(
    organization_id: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status", description="'success' or 'error'"),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> List[RequestLogResponse]:
    """Request-level history (Epic 4.6) - each row includes the full stage timeline
    (Epic 4.7) for debugging a specific slow or failed request."""
    query = select(RequestLog)
    if organization_id:
        query = query.where(RequestLog.organization_id == uuid.UUID(organization_id))
    if provider:
        query = query.where(RequestLog.selected_provider == provider.lower())
    if status_filter:
        query = query.where(RequestLog.status == status_filter)
    if since:
        query = query.where(RequestLog.created_at >= since)
    if until:
        query = query.where(RequestLog.created_at <= until)

    query = query.order_by(RequestLog.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return [_to_response(r) for r in result.scalars().all()]


def _apply_common_filters(query, organization_id: Optional[str], since: Optional[datetime], until: Optional[datetime]):
    if organization_id:
        query = query.where(RequestLog.organization_id == uuid.UUID(organization_id))
    if since:
        query = query.where(RequestLog.created_at >= since)
    if until:
        query = query.where(RequestLog.created_at <= until)
    return query


@router.get("/summary", response_model=AnalyticsSummary)
async def get_analytics_summary(
    organization_id: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> AnalyticsSummary:
    """Aggregate view backing the dashboard's Overview/Requests/Latency/Errors
    sections (Epic 4.9). Uses SQL-side aggregates (COUNT/AVG/SUM/GROUP BY via CASE,
    portable across SQLite and Postgres) instead of pulling every row into Python, so
    this stays cheap as request_logs grows."""
    totals_query = _apply_common_filters(
        select(
            func.count(RequestLog.id),
            func.sum(case((RequestLog.status == "success", 1), else_=0)),
            func.avg(RequestLog.latency_ms),
            func.sum(RequestLog.estimated_cost),
            func.sum(RequestLog.total_tokens),
            func.sum(case((RequestLog.cache_hit.is_(True), 1), else_=0)),
            func.sum(case((RequestLog.fallback_used.is_(True), 1), else_=0)),
        ),
        organization_id,
        since,
        until,
    )
    total, successes, avg_latency, total_cost, total_tokens, cache_hits, fallbacks = (
        await db.execute(totals_query)
    ).one()
    total = total or 0

    if total == 0:
        return AnalyticsSummary(
            total_requests=0,
            successful_requests=0,
            failed_requests=0,
            error_rate=0.0,
            avg_latency_ms=0.0,
            total_estimated_cost=0.0,
            total_tokens=0,
            cache_hit_rate=0.0,
            fallback_rate=0.0,
            by_provider=[],
        )

    successes = successes or 0
    failures = total - successes

    provider_query = _apply_common_filters(
        select(
            RequestLog.selected_provider,
            func.count(RequestLog.id),
            func.sum(case((RequestLog.status == "error", 1), else_=0)),
            func.avg(RequestLog.latency_ms),
            func.sum(RequestLog.estimated_cost),
        ).group_by(RequestLog.selected_provider),
        organization_id,
        since,
        until,
    ).order_by(func.count(RequestLog.id).desc())

    provider_rows = (await db.execute(provider_query)).all()
    by_provider = [
        ProviderBreakdown(
            provider=provider_name or "unknown",
            requests=requests,
            errors=errors or 0,
            avg_latency_ms=round(avg_lat or 0.0, 2),
            total_cost=round(cost_sum or 0.0, 6),
        )
        for provider_name, requests, errors, avg_lat, cost_sum in provider_rows
    ]

    return AnalyticsSummary(
        total_requests=total,
        successful_requests=successes,
        failed_requests=failures,
        error_rate=round((failures / total) * 100.0, 2),
        avg_latency_ms=round(avg_latency or 0.0, 2),
        total_estimated_cost=round(total_cost or 0.0, 6),
        total_tokens=total_tokens or 0,
        cache_hit_rate=round(((cache_hits or 0) / total) * 100.0, 2),
        fallback_rate=round(((fallbacks or 0) / total) * 100.0, 2),
        by_provider=by_provider,
    )
