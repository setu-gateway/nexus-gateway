from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import Float, Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProviderHealthMetricModel(Base):
    """Database table for persisting provider health metrics history."""

    __tablename__ = "provider_health_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider_name: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="online", nullable=False)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    success_rate: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    error_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    availability_score: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    total_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_successful_request: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
