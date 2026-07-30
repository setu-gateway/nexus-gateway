from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.gateway.db.base import Base

if TYPE_CHECKING:
    from apps.gateway.db.models.api_key import APIKey
    from apps.gateway.db.models.organization import Organization


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    """Project database model."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="projects")
    api_keys: Mapped[List["APIKey"]] = relationship("APIKey", back_populates="project", cascade="all, delete-orphan")
