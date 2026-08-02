import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimeMachineRecord(Base):
    """Epic 5.2 (flagship): full prompt+response capture for reproducibility, replay,
    and diffing. Deliberately separate from the default RequestLog (Epic 4.6/4.7),
    which minimizes payload retention by default per RFC-0006 ("privacy-aware, opt-in
    request replay") - a record here only exists because the caller explicitly opted
    in via X-Setu-Time-Machine: true.
    """

    __tablename__ = "time_machine_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)

    requested_model: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    upstream_model: Mapped[str] = mapped_column(String(255), nullable=False)

    request_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    request_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
