import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RateLimitRule(Base):
    """Configurable rate limit (Epic 5.4). `scope_type` names the dimension being
    limited; `scope_value` is that dimension's identifier and is null only for
    scope_type="global" (applies to every request). Multiple rules can be active at
    once (e.g. a global default plus a tighter per-project override) - a request is
    rejected if it violates ANY matching enabled rule.

    `limit`/`window_seconds` drive all three algorithms: fixed/sliding window use them
    directly, token bucket derives refill_rate = limit / window_seconds with burst
    capacity = limit - one schema instead of algorithm-specific columns.
    """

    __tablename__ = "rate_limit_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    scope_value: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    algorithm: Mapped[str] = mapped_column(String(20), nullable=False, default="sliding_window")
    limit: Mapped[int] = mapped_column(Integer, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
