import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RoutingRule(Base):
    """Organization-defined routing rule (Epic 4.2): a single `if <condition> then
    <action>` statement evaluated by apps/gateway/routing/rules.py before the router
    applies its ranking policy. Stored per-organization so rules stay isolated per
    RFC-0007 tenant isolation."""

    __tablename__ = "routing_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Condition: "<field> <operator> <value>", e.g. "latency > 500ms". Parsed by
    # apps/gateway/routing/rules.parse_condition - kept as one column for the exact
    # authoring syntax from the RFC/product spec rather than three loosely-related ones.
    condition_expression: Mapped[str] = mapped_column(String(255), nullable=False)

    # Action: "fallback" | "use" | "reject".
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    action_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)

    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
