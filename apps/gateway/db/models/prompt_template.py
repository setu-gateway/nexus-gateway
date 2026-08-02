import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.gateway.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PromptTemplate(Base):
    """An organization-scoped, reusable chat prompt with `{{variable}}` placeholders
    (Feature: Prompt Templates). `messages`/`current_version` hold the CURRENT live
    content; every content change is additionally snapshotted to
    PromptTemplateVersion, so `current_version` here always matches the newest row in
    that table for this template.
    """

    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class PromptTemplateVersion(Base):
    """Immutable snapshot of a PromptTemplate's content as of one point in its
    history. Written once at creation (version 1) and again on every content-changing
    update or rollback - never updated in place."""

    __tablename__ = "prompt_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_prompt_template_versions_template_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
