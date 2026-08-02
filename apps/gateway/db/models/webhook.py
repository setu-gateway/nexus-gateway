import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WebhookEndpoint(Base):
    """Customer-registered webhook target (Epic 5.7). `secret` is stored in
    recoverable (not hashed) form, unlike API keys - it has to be read back at
    delivery time to compute each request's HMAC signature."""

    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_types: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, doc="Subscribed event types. Null/empty = all events.")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    secret_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class WebhookDelivery(Base):
    """One row per delivery attempt-sequence (Epic 5.7) - the retry loop for a single
    event runs entirely before this is written, so `attempt_count` reflects the total
    tries and `status` reflects the final outcome, not each individual HTTP call."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    webhook_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "success" | "failed"
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
