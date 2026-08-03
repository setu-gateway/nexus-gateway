import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Policy(Base):
    """Organization-defined guardrail (Enterprise Policy Engine): unlike a
    RoutingRule, which picks *where* an eligible request goes, a Policy decides
    whether the request is eligible to be routed at all - evaluated once, before
    routing, by apps/gateway/policy/enforcement.py. A request that fails any enabled
    policy is rejected outright, not routed around it."""

    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # "provider_allowlist" | "provider_denylist" | "min_context_window" | "block_secrets"
    policy_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Shape depends on policy_type: {"providers": [...]} for allow/denylist,
    # {"min_context_window": 128000} for the context-window floor, {} for block_secrets
    # (its pattern set is fixed - see apps/gateway/policy/secrets.py).
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
