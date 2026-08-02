import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth import DashboardUserContext, Permission, require_permission
from apps.gateway.db.models import AuditLog
from apps.gateway.db.session import get_db_session

router = APIRouter(prefix="/audit-log", tags=["Audit Log"])


class AuditLogResponse(BaseModel):
    id: str
    actor: str
    organization_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    ip_address: str | None
    user_agent: str | None
    result: str
    details: dict[str, Any] | None
    created_at: datetime


def _to_response(log: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        id=str(log.id),
        actor=log.actor,
        organization_id=str(log.organization_id) if log.organization_id else None,
        action=log.action,
        resource_type=log.resource_type,
        resource_id=log.resource_id,
        ip_address=log.ip_address,
        user_agent=log.user_agent,
        result=log.result,
        details=log.details,
        created_at=log.created_at,
    )


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_log(
    organization_id: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    result: str | None = Query(default=None, description="'success' or 'failure'"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.VIEW_AUDIT_LOG)),
) -> list[AuditLogResponse]:
    """Immutable security/administration action history (Epic 5.8) - no update or
    delete endpoints are exposed on purpose. Always scoped to the caller's own
    organization - the audit log is exactly the kind of thing that must never leak
    across tenants."""
    if organization_id and not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view audit log for another organization")
    if not user.organization_id:
        return []

    query = select(AuditLog).where(AuditLog.organization_id == uuid.UUID(user.organization_id))
    if actor:
        query = query.where(AuditLog.actor == actor)
    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if result:
        query = query.where(AuditLog.result == result)
    if since:
        query = query.where(AuditLog.created_at >= since)
    if until:
        query = query.where(AuditLog.created_at <= until)

    query = query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    result_rows = await db.execute(query)
    return [_to_response(r) for r in result_rows.scalars().all()]
