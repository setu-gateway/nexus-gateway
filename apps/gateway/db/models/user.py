import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.gateway.db.base import Base

if TYPE_CHECKING:
    from apps.gateway.db.models.organization import Organization


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """User database model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Stores a rbac.Role value (owner/admin/developer/billing/security/viewer). Plain
    # str rather than a DB-native enum so adding a role later doesn't need a migration
    # that alters an enum type - apps/gateway/auth/rbac.py is the source of truth for
    # valid values.
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    organization: Mapped[Optional["Organization"]] = relationship("Organization", back_populates="users")
