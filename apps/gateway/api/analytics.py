import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth import KeyPermission, resolve_auth_or_401
from apps.gateway.db.models import RequestLog
from apps.gateway.db.session import get_db_session

router = APIRouter(prefix="/analytics", tags=["Analytics"])


async def _require_analytics_permission_if_authenticated(db: AsyncSession, authorization: str | None, client_ip: str | None) -> None:
    """Matches apps/gateway/api/openai_v1.py's posture (same resolve_auth_or_401 used
    there): auth stays optional so the dashboard's unauthenticated calls keep
    working, but a key that IS presented is still held to its scope."""
    await resolve_auth_or_401(db, authorization, client_ip, KeyPermission.ANALYTICS_READ)


class RequestLogResponse(BaseModel):
    id: str
    request_id: str
    organization_id: str | None
    project_id: str | None
    requested_model: str
    selected_provider: str | None
    routing_policy: str | None
    fallback_used: bool
    rule_applied: str | None
    status: str
    error_message: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    estimated_cost: float
    cache_hit: bool
    latency_ms: float
    timeline: dict[str, Any] | None
    created_at: datetime


class ProviderBreakdown(BaseModel):
    provider: str
    requests: int
    errors: int
    avg_latency_ms: float
    total_cost: float


class ModelBreakdown(BaseModel):
    model: str
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
    by_provider: list[ProviderBreakdown]
    top_models: list[ModelBreakdown]


def _to_response(row: RequestLog) -> RequestLogResponse:
    return RequestLogResponse(
        id=str(row.id),
        request_id=row.request_id,
        organization_id=str(row.organization_id) if row.organization_id else None,
        project_id=str(row.project_id) if row.project_id else None,
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


@router.get("/requests", response_model=list[RequestLogResponse])
async def list_request_logs(
    request: Request,
    organization_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None, description="Filter by requested (unified) model id"),
    status_filter: str | None = Query(default=None, alias="status", description="'success' or 'error'"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
    authorization: str | None = Header(default=None),
) -> list[RequestLogResponse]:
    """Request-level history (Epic 4.6) - each row includes the full stage timeline
    (Epic 4.7) for debugging a specific slow or failed request."""
    await _require_analytics_permission_if_authenticated(db, authorization, request.client.host if request.client else None)
    query = select(RequestLog)
    if organization_id:
        query = query.where(RequestLog.organization_id == uuid.UUID(organization_id))
    if project_id:
        query = query.where(RequestLog.project_id == uuid.UUID(project_id))
    if provider:
        query = query.where(RequestLog.selected_provider == provider.lower())
    if model:
        query = query.where(RequestLog.requested_model == model)
    if status_filter:
        query = query.where(RequestLog.status == status_filter)
    if since:
        query = query.where(RequestLog.created_at >= since)
    if until:
        query = query.where(RequestLog.created_at <= until)

    query = query.order_by(RequestLog.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return [_to_response(r) for r in result.scalars().all()]


def _apply_common_filters(
    query,
    organization_id: str | None,
    since: datetime | None,
    until: datetime | None,
    project_id: str | None = None,
    model: str | None = None,
):
    if organization_id:
        query = query.where(RequestLog.organization_id == uuid.UUID(organization_id))
    if project_id:
        query = query.where(RequestLog.project_id == uuid.UUID(project_id))
    if model:
        query = query.where(RequestLog.requested_model == model)
    if since:
        query = query.where(RequestLog.created_at >= since)
    if until:
        query = query.where(RequestLog.created_at <= until)
    return query


async def _grouped_breakdown(
    db: AsyncSession,
    group_by_column,
    organization_id: str | None,
    since: datetime | None,
    until: datetime | None,
    project_id: str | None,
    model: str | None,
    limit: int | None = None,
):
    """The count/errors/avg-latency/total-cost aggregate grouped by
    `group_by_column`, with the same request_logs filters as the summary's totals
    query - shared by the by-provider and top-models breakdowns below, which are
    identical except for which column they group by and whether they're capped with
    a limit. Returns raw (name, requests, errors, avg_latency_ms, total_cost) rows;
    the caller maps each into whichever breakdown model matches what it grouped by,
    since only the caller knows the field name and null-handling for that column.
    """
    query = _apply_common_filters(
        select(
            group_by_column,
            func.count(RequestLog.id),
            func.sum(case((RequestLog.status == "error", 1), else_=0)),
            func.avg(RequestLog.latency_ms),
            func.sum(RequestLog.estimated_cost),
        ).group_by(group_by_column),
        organization_id,
        since,
        until,
        project_id,
        model,
    ).order_by(func.count(RequestLog.id).desc())
    if limit is not None:
        query = query.limit(limit)
    return (await db.execute(query)).all()


@router.get("/summary", response_model=AnalyticsSummary)
async def get_analytics_summary(
    request: Request,
    organization_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    model: str | None = Query(default=None, description="Filter by requested (unified) model id"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    top_models_limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db_session),
    authorization: str | None = Header(default=None),
) -> AnalyticsSummary:
    """Aggregate view backing the dashboard's Overview/Requests/Latency/Errors
    sections (Epic 4.9). Uses SQL-side aggregates (COUNT/AVG/SUM/GROUP BY via CASE,
    portable across SQLite and Postgres) instead of pulling every row into Python, so
    this stays cheap as request_logs grows."""
    await _require_analytics_permission_if_authenticated(db, authorization, request.client.host if request.client else None)
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
        project_id,
        model,
    )
    total, successes, avg_latency, total_cost, total_tokens, cache_hits, fallbacks = (await db.execute(totals_query)).one()
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
            top_models=[],
        )

    successes = successes or 0
    failures = total - successes

    provider_rows = await _grouped_breakdown(db, RequestLog.selected_provider, organization_id, since, until, project_id, model)
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

    model_rows = await _grouped_breakdown(
        db, RequestLog.requested_model, organization_id, since, until, project_id, model, limit=top_models_limit
    )
    top_models = [
        ModelBreakdown(
            model=model_name,
            requests=requests,
            errors=errors or 0,
            avg_latency_ms=round(avg_lat or 0.0, 2),
            total_cost=round(cost_sum or 0.0, 6),
        )
        for model_name, requests, errors, avg_lat, cost_sum in model_rows
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
        top_models=top_models,
    )
