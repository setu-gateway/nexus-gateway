import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvalSuite(Base):
    """A named, organization-scoped collection of evaluation cases (Flagship: AI
    Evaluation Engine). Suites are re-run over time (often against different models)
    to catch prompt/model regressions - see EvalRun."""

    __tablename__ = "eval_suites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class EvalCase(Base):
    """One test case within a suite: an input to send and how to score the response.

    `expected_output` and `scorer_config` are intentionally untyped JSON since their
    shape depends on `scorer_type` (e.g. a string for exact_match, a list of substrings
    for contains, a JSON Schema object for structured_output) - see
    apps/gateway/evaluation/scorers.py for the shape each scorer expects.
    """

    __tablename__ = "eval_cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    suite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_suites.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    scorer_type: Mapped[str] = mapped_column(String(50), nullable=False)
    expected_output: Mapped[Any] = mapped_column(JSON, nullable=False)
    scorer_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class EvalRun(Base):
    """One execution of a suite's cases against a single model (Flagship: AI Evaluation
    Engine). Runs are triggered synchronously but executed as a background task -
    `status` starts "pending", moves to "running", and settles at "completed" or
    "failed" (the latter only for an infrastructure-level failure that aborted the
    whole run, not individual case failures - those are captured per-EvalResult).

    `suite_id` is nullable/SET NULL and `suite_name` is captured at creation time so a
    run's historical results and cost data survive deletion of the suite that produced
    them, the same reasoning as RequestLog.project_id.
    """

    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    suite_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("eval_suites.id", ondelete="SET NULL"), nullable=True, index=True)
    suite_name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalResult(Base):
    """The outcome of a single case within a run. `case_id` is nullable/SET NULL and
    `case_name` is captured at execution time for the same reason EvalRun keeps
    `suite_name` - deleting a case shouldn't erase what a past run showed for it.
    """

    __tablename__ = "eval_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("eval_cases.id", ondelete="SET NULL"), nullable=True, index=True)
    case_name: Mapped[str] = mapped_column(String(255), nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    actual_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
