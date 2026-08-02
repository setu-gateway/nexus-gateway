import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.audit import record_audit_event
from apps.gateway.auth import DashboardUserContext, Permission, require_permission, resolve_dashboard_user_or_401
from apps.gateway.db.models import EvalCase, EvalResult, EvalRun, EvalSuite
from apps.gateway.db.session import get_db_session
from apps.gateway.evaluation import execute_eval_run, validate_case_definition
from apps.gateway.utils import fire_and_forget

router = APIRouter(prefix="/eval", tags=["Evaluation"])


def _audit_ctx(request: Request) -> dict:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


# ---------------------------------------------------------------------------
# Suites
# ---------------------------------------------------------------------------


class EvalSuiteCreate(BaseModel):
    organization_id: str
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class EvalSuiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class EvalSuiteResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str | None
    case_count: int
    created_at: datetime
    updated_at: datetime


def _suite_to_response(suite: EvalSuite, case_count: int) -> EvalSuiteResponse:
    return EvalSuiteResponse(
        id=str(suite.id),
        organization_id=str(suite.organization_id),
        name=suite.name,
        description=suite.description,
        case_count=case_count,
        created_at=suite.created_at,
        updated_at=suite.updated_at,
    )


async def _get_suite_or_404(suite_id: str, db: AsyncSession, user: DashboardUserContext) -> EvalSuite:
    try:
        suite_uuid = uuid.UUID(suite_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid suite id: '{suite_id}'") from None
    suite = await db.get(EvalSuite, suite_uuid)
    if not suite or not user.owns_organization(str(suite.organization_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Eval suite '{suite_id}' not found")
    return suite


async def _case_count(suite_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(EvalCase).where(EvalCase.suite_id == suite_id))
    return result.scalar_one()


@router.post("/suites", response_model=EvalSuiteResponse, status_code=status.HTTP_201_CREATED)
async def create_eval_suite(
    req: EvalSuiteCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.RUN_EVALUATIONS)),
) -> EvalSuiteResponse:
    if not user.owns_organization(req.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create an eval suite for another organization")
    suite = EvalSuite(id=uuid.uuid4(), organization_id=uuid.UUID(req.organization_id), name=req.name, description=req.description)
    db.add(suite)
    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="eval_suite.created",
            resource_type="eval_suite",
            resource_id=str(suite.id),
            organization_id=str(suite.organization_id),
            details={"name": suite.name},
            **_audit_ctx(request),
        )
    )
    return _suite_to_response(suite, 0)


@router.get("/suites", response_model=list[EvalSuiteResponse])
async def list_eval_suites(
    organization_id: str = Query(description="Organization UUID to list suites for"),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[EvalSuiteResponse]:
    if not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot list eval suites for another organization")
    result = await db.execute(
        select(EvalSuite).where(EvalSuite.organization_id == uuid.UUID(organization_id)).order_by(EvalSuite.created_at.desc())
    )
    suites = result.scalars().all()
    return [_suite_to_response(s, await _case_count(s.id, db)) for s in suites]


@router.get("/suites/{suite_id}", response_model=EvalSuiteResponse)
async def get_eval_suite(
    suite_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> EvalSuiteResponse:
    suite = await _get_suite_or_404(suite_id, db, user)
    return _suite_to_response(suite, await _case_count(suite.id, db))


@router.patch("/suites/{suite_id}", response_model=EvalSuiteResponse)
async def update_eval_suite(
    suite_id: str,
    req: EvalSuiteUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.RUN_EVALUATIONS)),
) -> EvalSuiteResponse:
    suite = await _get_suite_or_404(suite_id, db, user)
    if req.name is not None:
        suite.name = req.name
    if req.description is not None:
        suite.description = req.description
    await db.flush()

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="eval_suite.updated",
            resource_type="eval_suite",
            resource_id=str(suite.id),
            organization_id=str(suite.organization_id),
            details=req.model_dump(exclude_none=True),
            **_audit_ctx(request),
        )
    )
    return _suite_to_response(suite, await _case_count(suite.id, db))


@router.delete("/suites/{suite_id}", status_code=status.HTTP_200_OK)
async def delete_eval_suite(
    suite_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.RUN_EVALUATIONS)),
) -> dict:
    suite = await _get_suite_or_404(suite_id, db, user)
    organization_id = str(suite.organization_id)
    await db.delete(suite)

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="eval_suite.deleted",
            resource_type="eval_suite",
            resource_id=suite_id,
            organization_id=organization_id,
            **_audit_ctx(request),
        )
    )
    return {"message": f"Eval suite '{suite_id}' deleted successfully"}


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def _validate_messages_shape(v: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for m in v:
        if "role" not in m or "content" not in m:
            raise ValueError("each message must have 'role' and 'content'")
    return v


class EvalCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    messages: list[dict[str, Any]] = Field(min_length=1, description="Chat messages to send, same shape as /v1/chat/completions")
    scorer_type: str = Field(description="exact_match | contains | structured_output | tool_call_success")
    expected_output: Any = Field(description="Shape depends on scorer_type - see scorer docstrings")
    scorer_config: dict[str, Any] | None = None

    @field_validator("messages")
    @classmethod
    def _validate_messages(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _validate_messages_shape(v)


class EvalCaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    messages: list[dict[str, Any]] | None = Field(default=None, min_length=1)
    scorer_type: str | None = None
    expected_output: Any | None = None
    scorer_config: dict[str, Any] | None = None

    @field_validator("messages")
    @classmethod
    def _validate_messages(cls, v: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        return _validate_messages_shape(v) if v is not None else v


class EvalCaseResponse(BaseModel):
    id: str
    suite_id: str
    name: str
    messages: list[dict[str, Any]]
    scorer_type: str
    expected_output: Any
    scorer_config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


def _case_to_response(case: EvalCase) -> EvalCaseResponse:
    return EvalCaseResponse(
        id=str(case.id),
        suite_id=str(case.suite_id),
        name=case.name,
        messages=case.messages,
        scorer_type=case.scorer_type,
        expected_output=case.expected_output,
        scorer_config=case.scorer_config,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


async def _get_case_or_404(case_id: str, db: AsyncSession, user: DashboardUserContext) -> EvalCase:
    try:
        case_uuid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid case id: '{case_id}'") from None
    case = await db.get(EvalCase, case_uuid)
    if case is not None:
        # EvalCase has no organization_id of its own - ownership flows through its suite.
        await _get_suite_or_404(str(case.suite_id), db, user)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Eval case '{case_id}' not found")
    return case


def _validate_or_400(scorer_type: str, expected_output: Any) -> None:
    try:
        validate_case_definition(scorer_type, expected_output)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/suites/{suite_id}/cases", response_model=EvalCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_eval_case(
    suite_id: str,
    req: EvalCaseCreate,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.RUN_EVALUATIONS)),
) -> EvalCaseResponse:
    suite = await _get_suite_or_404(suite_id, db, user)
    _validate_or_400(req.scorer_type, req.expected_output)

    case = EvalCase(
        id=uuid.uuid4(),
        suite_id=suite.id,
        name=req.name,
        messages=req.messages,
        scorer_type=req.scorer_type,
        expected_output=req.expected_output,
        scorer_config=req.scorer_config,
    )
    db.add(case)
    await db.flush()
    return _case_to_response(case)


@router.get("/suites/{suite_id}/cases", response_model=list[EvalCaseResponse])
async def list_eval_cases(
    suite_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> list[EvalCaseResponse]:
    suite = await _get_suite_or_404(suite_id, db, user)
    result = await db.execute(select(EvalCase).where(EvalCase.suite_id == suite.id).order_by(EvalCase.created_at))
    return [_case_to_response(c) for c in result.scalars().all()]


@router.get("/cases/{case_id}", response_model=EvalCaseResponse)
async def get_eval_case(
    case_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> EvalCaseResponse:
    case = await _get_case_or_404(case_id, db, user)
    return _case_to_response(case)


@router.patch("/cases/{case_id}", response_model=EvalCaseResponse)
async def update_eval_case(
    case_id: str,
    req: EvalCaseUpdate,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.RUN_EVALUATIONS)),
) -> EvalCaseResponse:
    case = await _get_case_or_404(case_id, db, user)

    new_scorer_type = req.scorer_type if req.scorer_type is not None else case.scorer_type
    new_expected_output = req.expected_output if req.expected_output is not None else case.expected_output
    if req.scorer_type is not None or req.expected_output is not None:
        _validate_or_400(new_scorer_type, new_expected_output)

    if req.name is not None:
        case.name = req.name
    if req.messages is not None:
        case.messages = req.messages
    if req.scorer_type is not None:
        case.scorer_type = req.scorer_type
    if req.expected_output is not None:
        case.expected_output = req.expected_output
    if req.scorer_config is not None:
        case.scorer_config = req.scorer_config
    await db.flush()
    return _case_to_response(case)


@router.delete("/cases/{case_id}", status_code=status.HTTP_200_OK)
async def delete_eval_case(
    case_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.RUN_EVALUATIONS)),
) -> dict:
    case = await _get_case_or_404(case_id, db, user)
    await db.delete(case)
    return {"message": f"Eval case '{case_id}' deleted successfully"}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class EvalRunCreate(BaseModel):
    suite_id: str
    model: str = Field(min_length=1, description="Unified model id to evaluate, e.g. 'gpt-4o'")


class EvalRunResponse(BaseModel):
    id: str
    suite_id: str | None
    suite_name: str
    organization_id: str
    model: str
    status: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    avg_latency_ms: float | None
    total_cost_usd: float | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class EvalResultResponse(BaseModel):
    id: str
    run_id: str
    case_id: str | None
    case_name: str
    passed: bool
    score: float
    actual_output: str | None
    latency_ms: float | None
    cost_usd: float | None
    error_message: str | None
    details: dict[str, Any] | None
    created_at: datetime


def _run_to_response(run: EvalRun) -> EvalRunResponse:
    return EvalRunResponse(
        id=str(run.id),
        suite_id=str(run.suite_id) if run.suite_id else None,
        suite_name=run.suite_name,
        organization_id=str(run.organization_id),
        model=run.model,
        status=run.status,
        total_cases=run.total_cases,
        passed_cases=run.passed_cases,
        failed_cases=run.failed_cases,
        avg_latency_ms=run.avg_latency_ms,
        total_cost_usd=run.total_cost_usd,
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _result_to_response(r: EvalResult) -> EvalResultResponse:
    return EvalResultResponse(
        id=str(r.id),
        run_id=str(r.run_id),
        case_id=str(r.case_id) if r.case_id else None,
        case_name=r.case_name,
        passed=r.passed,
        score=r.score,
        actual_output=r.actual_output,
        latency_ms=r.latency_ms,
        cost_usd=r.cost_usd,
        error_message=r.error_message,
        details=r.details,
        created_at=r.created_at,
    )


async def _get_run_or_404(run_id: str, db: AsyncSession, user: DashboardUserContext) -> EvalRun:
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid run id: '{run_id}'") from None
    run = await db.get(EvalRun, run_uuid)
    if not run or not user.owns_organization(str(run.organization_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Eval run '{run_id}' not found")
    return run


@router.post("/runs", response_model=EvalRunResponse, status_code=status.HTTP_201_CREATED)
async def create_eval_run(
    req: EvalRunCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.RUN_EVALUATIONS)),
) -> EvalRunResponse:
    """Kicks off a run of a suite's cases against `model` and returns immediately with
    status="pending" - execution (real provider calls, one per case) happens in the
    background; poll GET /eval/runs/{id} or GET /eval/runs/{id}/results for progress.
    """
    suite = await _get_suite_or_404(req.suite_id, db, user)
    case_count = await _case_count(suite.id, db)
    if case_count == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Suite has no cases to run")

    run = EvalRun(
        id=uuid.uuid4(),
        suite_id=suite.id,
        suite_name=suite.name,
        organization_id=suite.organization_id,
        model=req.model,
        status="pending",
        total_cases=case_count,
    )
    db.add(run)
    await db.flush()
    # execute_eval_run opens its own standalone session(s) - the request-scoped `db`
    # session above must be committed first so the run row it just wrote is visible
    # to the background task's own session (same reasoning as chat_completions'
    # post-auth commit).
    await db.commit()

    fire_and_forget(execute_eval_run(run.id))

    fire_and_forget(
        record_audit_event(
            actor=user.email,
            action="eval_run.created",
            resource_type="eval_run",
            resource_id=str(run.id),
            organization_id=str(run.organization_id),
            details={"suite_id": str(suite.id), "model": run.model},
            **_audit_ctx(request),
        )
    )
    return _run_to_response(run)


@router.get("/runs/{run_id}", response_model=EvalRunResponse)
async def get_eval_run(
    run_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> EvalRunResponse:
    run = await _get_run_or_404(run_id, db, user)
    return _run_to_response(run)


@router.get("/runs/{run_id}/results", response_model=list[EvalResultResponse])
async def list_eval_results(
    run_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> list[EvalResultResponse]:
    await _get_run_or_404(run_id, db, user)
    result = await db.execute(select(EvalResult).where(EvalResult.run_id == uuid.UUID(run_id)).order_by(EvalResult.created_at))
    return [_result_to_response(r) for r in result.scalars().all()]


@router.get("/suites/{suite_id}/runs", response_model=list[EvalRunResponse])
async def list_eval_runs_for_suite(
    suite_id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> list[EvalRunResponse]:
    """Run history for a suite, most recent first - the primary view for tracking
    pass-rate/cost/latency trends across models or over time as prompts change."""
    suite = await _get_suite_or_404(suite_id, db, user)
    result = await db.execute(select(EvalRun).where(EvalRun.suite_id == suite.id).order_by(EvalRun.started_at.desc()))
    return [_run_to_response(r) for r in result.scalars().all()]


@router.delete("/runs/{run_id}", status_code=status.HTTP_200_OK)
async def delete_eval_run(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.RUN_EVALUATIONS)),
) -> dict:
    run = await _get_run_or_404(run_id, db, user)
    await db.delete(run)
    return {"message": f"Eval run '{run_id}' deleted successfully"}
