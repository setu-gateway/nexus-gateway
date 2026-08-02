import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.audit import record_audit_event
from apps.gateway.auth import DashboardUserContext, resolve_dashboard_user_or_401
from apps.gateway.comparison import run_comparison
from apps.gateway.db.models import ComparisonResult, ComparisonRun
from apps.gateway.db.session import get_db_session
from apps.gateway.providers.instance import model_registry, provider_registry
from apps.gateway.utils import fire_and_forget

router = APIRouter(prefix="/comparisons", tags=["Request Comparison"])


def _audit_ctx(request: Request) -> dict:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


class ComparisonCreate(BaseModel):
    organization_id: str
    name: str | None = Field(default=None, max_length=255)
    messages: list[dict[str, Any]] = Field(min_length=1, description="Same shape as /v1/chat/completions messages")
    models: list[str] = Field(min_length=2, description="Unified model ids to compare, e.g. ['gpt-4o', 'claude-3-5-sonnet']")
    temperature: float | None = 0.7
    top_p: float | None = 1.0
    max_tokens: int | None = None

    @field_validator("messages")
    @classmethod
    def _validate_messages(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for m in v:
            if "role" not in m or "content" not in m:
                raise ValueError("each message must have 'role' and 'content'")
        return v

    @field_validator("models")
    @classmethod
    def _validate_models(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("models must not contain duplicates")
        return v


class ComparisonResultResponse(BaseModel):
    id: str
    model: str
    provider: str
    upstream_model: str
    success: bool
    response_text: str | None
    latency_ms: float
    cost_usd: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None


class ComparisonRunSummary(BaseModel):
    id: str
    organization_id: str
    name: str | None
    models: list[str]
    created_at: datetime


class ComparisonRunDetail(ComparisonRunSummary):
    messages: list[dict[str, Any]]
    results: list[ComparisonResultResponse]


def _result_to_response(r: ComparisonResult) -> ComparisonResultResponse:
    return ComparisonResultResponse(
        id=str(r.id),
        model=r.model,
        provider=r.provider,
        upstream_model=r.upstream_model,
        success=r.success,
        response_text=r.response_text,
        latency_ms=r.latency_ms,
        cost_usd=r.cost_usd,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
        error=r.error,
    )


def _run_to_summary(run: ComparisonRun) -> ComparisonRunSummary:
    return ComparisonRunSummary(
        id=str(run.id), organization_id=str(run.organization_id), name=run.name, models=run.models, created_at=run.created_at
    )


async def _get_run_or_404(run_id: str, db: AsyncSession, user: DashboardUserContext) -> ComparisonRun:
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid comparison id: '{run_id}'") from None
    run = await db.get(ComparisonRun, run_uuid)
    if not run or not user.owns_organization(str(run.organization_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Comparison '{run_id}' not found")
    return run


@router.post("", response_model=ComparisonRunDetail, status_code=status.HTTP_201_CREATED)
async def create_comparison(
    req: ComparisonCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> ComparisonRunDetail:
    """Runs `messages` against every model in `models` concurrently (via
    apps/gateway/comparison/service.py, built on Epic 4's replay_request) and saves
    the side-by-side result. Fast enough (a handful of concurrent provider calls,
    same order of magnitude as one chat completion) to run inline rather than as a
    background task like eval runs - the response already contains full results.
    """
    if not user.owns_organization(req.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create a comparison for another organization")

    candidate_results = await run_comparison(
        provider_registry,
        model_registry,
        req.models,
        req.messages,
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
    )

    run = ComparisonRun(
        id=uuid.uuid4(),
        organization_id=uuid.UUID(req.organization_id),
        name=req.name,
        messages=req.messages,
        models=req.models,
    )
    db.add(run)
    await db.flush()

    result_rows = [
        ComparisonResult(
            id=uuid.uuid4(),
            run_id=run.id,
            model=c.model,
            provider=c.provider,
            upstream_model=c.upstream_model,
            success=c.success,
            response_text=c.response_text,
            latency_ms=c.latency_ms,
            cost_usd=c.cost_usd,
            prompt_tokens=c.prompt_tokens,
            completion_tokens=c.completion_tokens,
            error=c.error,
        )
        for c in candidate_results
    ]
    db.add_all(result_rows)
    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="comparison.created",
            resource_type="comparison_run",
            resource_id=str(run.id),
            organization_id=str(run.organization_id),
            details={"models": req.models},
            **_audit_ctx(request),
        )
    )

    return ComparisonRunDetail(
        **_run_to_summary(run).model_dump(), messages=run.messages, results=[_result_to_response(r) for r in result_rows]
    )


@router.get("", response_model=list[ComparisonRunSummary])
async def list_comparisons(
    organization_id: str = Query(description="Organization UUID to list comparisons for"),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[ComparisonRunSummary]:
    if not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot list comparisons for another organization")
    result = await db.execute(
        select(ComparisonRun).where(ComparisonRun.organization_id == uuid.UUID(organization_id)).order_by(ComparisonRun.created_at.desc())
    )
    return [_run_to_summary(r) for r in result.scalars().all()]


@router.get("/{run_id}", response_model=ComparisonRunDetail)
async def get_comparison(
    run_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> ComparisonRunDetail:
    run = await _get_run_or_404(run_id, db, user)
    result = await db.execute(select(ComparisonResult).where(ComparisonResult.run_id == run.id).order_by(ComparisonResult.created_at))
    results = result.scalars().all()
    return ComparisonRunDetail(
        **_run_to_summary(run).model_dump(), messages=run.messages, results=[_result_to_response(r) for r in results]
    )


@router.delete("/{run_id}", status_code=status.HTTP_200_OK)
async def delete_comparison(
    run_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> dict:
    run = await _get_run_or_404(run_id, db, user)
    await db.delete(run)
    return {"message": f"Comparison '{run_id}' deleted successfully"}
