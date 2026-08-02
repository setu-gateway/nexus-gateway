import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.gateway.db.base import Base

if TYPE_CHECKING:
    from apps.gateway.db.models.project import Project


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class APIKey(Base):
    """API Key database model."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="Default Key", nullable=False)
    hashed_key: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    masked_key: Mapped[str] = mapped_column(String(50), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Epic 5.3 - Scoped API keys. Every restriction column is nullable and a null/empty
    # value means "unrestricted", so keys issued before this feature keep working exactly
    # as before (RFC-0007's zero-trust posture is opt-in tightening, not a breaking change).
    permissions: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, doc="Allowed operations (see apps.gateway.auth.permissions.Permission). Null = all."
    )
    allowed_ips: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, doc="IPv4/IPv6 addresses or CIDR ranges this key may be used from. Null = any."
    )
    allowed_providers: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, doc="Provider names this key may route to. Null = any."
    )
    allowed_models: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, doc="Upstream model ids this key may request. Null = any."
    )
    rate_limit_per_minute: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="Per-key request budget enforced by the rate limiter (Epic 5.4). Null = unlimited."
    )

    project: Mapped["Project"] = relationship("Project", back_populates="api_keys")
