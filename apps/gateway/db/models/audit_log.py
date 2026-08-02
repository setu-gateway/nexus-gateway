import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(Base):
    """Immutable record of a security/administration-relevant action (Epic 5.8).
    `actor` is a free-form identifier (user email, "api_key:<id>", or "anonymous" for
    endpoints without auth today) rather than a foreign key, since not every action
    that needs auditing has a resolvable User row (e.g. a request authenticated by
    API key, or an endpoint with no auth wired up yet)."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    result: Mapped[str] = mapped_column(String(20), nullable=False)  # "success" | "failure"
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
