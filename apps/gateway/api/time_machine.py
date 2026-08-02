import uuid
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth import DashboardUserContext, resolve_dashboard_user_or_401
from apps.gateway.db.models import TimeMachineRecord
from apps.gateway.db.session import get_db_session
from apps.gateway.providers.instance import model_registry, provider_registry
from apps.gateway.routing.replay import replay_request

router = APIRouter(prefix="/time-machine", tags=["Time Machine"])


class TimeMachineRecordResponse(BaseModel):
    id: str
    request_id: str
    organization_id: str | None
    project_id: str | None
    requested_model: str
    provider: str
    upstream_model: str
    request_messages: list[dict[str, Any]]
    request_params: dict[str, Any]
    response_body: dict[str, Any]
    latency_ms: float
    estimated_cost: float
    created_at: datetime


class ReplayResultView(BaseModel):
    provider: str
    upstream_model: str
    success: bool
    response_content: str | None
    error: str | None
    latency_ms: float


class TimeMachineReplayResponse(BaseModel):
    request_id: str
    original: ReplayResultView
    replayed: ReplayResultView
    diff_ratio: float
    diff: list[str]


def _to_response(r: TimeMachineRecord) -> TimeMachineRecordResponse:
    return TimeMachineRecordResponse(
        id=str(r.id),
        request_id=r.request_id,
        organization_id=str(r.organization_id) if r.organization_id else None,
        project_id=str(r.project_id) if r.project_id else None,
        requested_model=r.requested_model,
        provider=r.provider,
        upstream_model=r.upstream_model,
        request_messages=r.request_messages,
        request_params=r.request_params,
        response_body=r.response_body,
        latency_ms=r.latency_ms,
        estimated_cost=r.estimated_cost,
        created_at=r.created_at,
    )


def _extract_text(response_body: dict[str, Any] | None) -> str:
    if not response_body:
        return ""
    try:
        return response_body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return str(response_body)


async def _get_record_or_404(request_id: str, db: AsyncSession, user: DashboardUserContext) -> TimeMachineRecord:
    result = await db.execute(select(TimeMachineRecord).where(TimeMachineRecord.request_id == request_id))
    record = result.scalar_one_or_none()
    # Time Machine records hold full request/response bodies - real prompt content -
    # so a record with no organization_id (pre-auth traffic, or a record that somehow
    # lost its tenant) is hidden rather than shown to everyone by default.
    if not record or not user.owns_organization(str(record.organization_id) if record.organization_id else None):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No Time Machine record for '{request_id}'")
    return record


@router.get("", response_model=list[TimeMachineRecordResponse])
async def list_time_machine_records(
    organization_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[TimeMachineRecordResponse]:
    if organization_id and not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot list Time Machine records for another organization")
    if not user.organization_id:
        return []

    query = (
        select(TimeMachineRecord)
        .where(TimeMachineRecord.organization_id == uuid.UUID(user.organization_id))
        .order_by(TimeMachineRecord.created_at.desc())
        .limit(limit)
    )
    if project_id:
        query = query.where(TimeMachineRecord.project_id == uuid.UUID(project_id))
    result = await db.execute(query)
    return [_to_response(r) for r in result.scalars().all()]


@router.get("/{request_id}", response_model=TimeMachineRecordResponse)
async def get_time_machine_record(
    request_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> TimeMachineRecordResponse:
    return _to_response(await _get_record_or_404(request_id, db, user))


@router.post("/{request_id}/replay", response_model=TimeMachineReplayResponse)
async def replay_time_machine_record(
    request_id: str,
    provider: str | None = Query(default=None, description="Replay against a different provider; defaults to the original"),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> TimeMachineReplayResponse:
    """Debugging, regression testing, prompt engineering (Epic 5.2): re-run a stored
    request - by default against the same provider, to check for drift over time, or
    against a different one to compare - and diff the two responses."""
    record = await _get_record_or_404(request_id, db, user)

    target_provider = (provider or record.provider).lower()
    if target_provider == record.provider:
        target_upstream_model = record.upstream_model
    else:
        equivalents = model_registry.find_equivalents(record.requested_model)
        match = next((m for m in equivalents if m.provider_name == target_provider), None)
        target_upstream_model = match.provider_model_id if match else record.requested_model

    results = await replay_request(
        provider_registry,
        [(target_provider, target_upstream_model)],
        record.request_messages,
        temperature=record.request_params.get("temperature"),
        top_p=record.request_params.get("top_p"),
        max_tokens=record.request_params.get("max_tokens"),
    )
    replayed = results[0]

    original_text = _extract_text(record.response_body)
    replayed_text = _extract_text(replayed.response) if replayed.success else ""
    matcher = SequenceMatcher(None, original_text, replayed_text)

    return TimeMachineReplayResponse(
        request_id=request_id,
        original=ReplayResultView(
            provider=record.provider,
            upstream_model=record.upstream_model,
            success=True,
            response_content=original_text,
            error=None,
            latency_ms=record.latency_ms,
        ),
        replayed=ReplayResultView(
            provider=replayed.provider,
            upstream_model=replayed.upstream_model,
            success=replayed.success,
            response_content=replayed_text if replayed.success else None,
            error=replayed.error,
            latency_ms=replayed.latency_ms,
        ),
        diff_ratio=round(matcher.ratio(), 4),
        diff=_unified_diff_lines(original_text, replayed_text),
    )


def _unified_diff_lines(a: str, b: str) -> list[str]:
    import difflib

    return list(difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", fromfile="original", tofile="replayed"))
