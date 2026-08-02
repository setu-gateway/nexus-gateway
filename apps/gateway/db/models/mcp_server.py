import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MCPServer(Base):
    """An organization-registered MCP (Model Context Protocol) server the gateway can
    discover tools from and invoke tools on, over MCP's Streamable HTTP transport
    (Feature: MCP support). `headers` carries whatever the server needs for auth
    (e.g. `{"Authorization": "Bearer ..."}`) and is stored in recoverable form like
    WebhookEndpoint.secret - it has to be replayed on every call, not just verified
    once.

    `last_health_*` fields are written by GET/POST .../health, not by any background
    poller - this is a foundation for on-demand and dashboard-triggered checks, not a
    continuous monitor.
    """

    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    headers: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_health_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "ok" | "error"
    last_health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
