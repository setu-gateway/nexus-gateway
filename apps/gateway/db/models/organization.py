import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.gateway.db.base import Base

if TYPE_CHECKING:
    from apps.gateway.db.models.project import Project
    from apps.gateway.db.models.user import User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    """Organization database model."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="free", nullable=False)
    # Epic 5.6 - billing foundation. Nullable = unlimited. Tracking/visibility only:
    # the gateway records usage against these and surfaces it via
    # GET /organizations/{id}/usage, but never rejects a request for being over quota -
    # that's a deliberately separate, later decision (payment enforcement).
    monthly_request_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_spend_quota_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    users: Mapped[list["User"]] = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship("Project", back_populates="organization", cascade="all, delete-orphan")
