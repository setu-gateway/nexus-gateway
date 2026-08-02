import uuid
from typing import Any

from apps.gateway.db import session as db_session_module
from apps.gateway.db.models import AuditLog
from apps.gateway.db.retry import with_lock_retry
from packages.shared.logging.logger import get_logger

logger = get_logger("audit_recorder")


async def record_audit_event(
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    organization_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    result: str = "success",
    details: dict[str, Any] | None = None,
) -> None:
    """Persist one AuditLog row (Epic 5.8). Opens its own session, same pattern as
    apps/gateway/analytics/recorder.py and for the same reason: a failed/rejected
    action (e.g. a failed login) is exactly the one most worth keeping a record of,
    so this must not ride a session that rolls back with the request. Never raises -
    a lost audit entry shouldn't take down the action it was describing.
    """

    async def _write() -> None:
        async with db_session_module.async_session_factory() as session:
            session.add(
                AuditLog(
                    id=uuid.uuid4(),
                    actor=actor,
                    organization_id=uuid.UUID(organization_id) if organization_id else None,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    result=result,
                    details=details,
                )
            )
            await session.commit()

    try:
        await with_lock_retry(_write)
    except Exception as e:
        logger.warning(f"Failed to record audit event action={action} resource_type={resource_type}: {e}")
