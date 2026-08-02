import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CacheEntry(Base):
    """Persistent (Postgres) tier of the intelligent cache (Epic 5.1) - the backstop
    tier below Memory and Redis, so a cache-warm restart doesn't cold-start every key."""

    __tablename__ = "cache_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_streaming: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stream_chunks: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class CachePolicy(Base):
    """Per-project cache policy (Epic 5.1). Absent row = use global defaults."""

    __tablename__ = "cache_policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=3600, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
