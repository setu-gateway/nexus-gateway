import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ComparisonRun(Base):
    """One side-by-side comparison of the same prompt across several models (Feature:
    Request Comparison). Unlike Epic 4's /routing/replay - a stateless diagnostic
    primitive this feature is built on top of, not a replacement for - a
    ComparisonRun is saved, so a comparison can be revisited later instead of only
    living in one response payload."""

    __tablename__ = "comparison_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    models: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class ComparisonResult(Base):
    """One model's outcome within a ComparisonRun."""

    __tablename__ = "comparison_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("comparison_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    upstream_model: Mapped[str] = mapped_column(String(255), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
