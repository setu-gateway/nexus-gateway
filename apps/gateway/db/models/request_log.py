import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RequestLog(Base):
    """Per-request analytics record (Epic 4.6) with an embedded stage timeline
    (Epic 4.7). One row per gateway request, written after routing/execution
    completes (or fails) so historical dashboards and debugging both read from the
    same source of truth."""

    __tablename__ = "request_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)

    requested_model: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    selected_provider: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    routing_policy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rule_applied: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # "success" | "error"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    timeline: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
