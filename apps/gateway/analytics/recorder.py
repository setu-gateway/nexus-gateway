import uuid

from apps.gateway.analytics.timeline import RequestTimeline
from apps.gateway.db import session as db_session_module
from apps.gateway.db.models import RequestLog
from apps.gateway.db.retry import with_lock_retry
from apps.gateway.utils import fire_and_forget
from apps.gateway.webhooks import WebhookEvent, check_and_dispatch_quota_exceeded, dispatch_webhook_event
from packages.shared.logging.logger import get_logger

logger = get_logger("analytics_recorder")


async def record_request(
    *,
    request_id: str,
    requested_model: str,
    status: str,
    timeline: RequestTimeline,
    organization_id: str | None = None,
    project_id: str | None = None,
    selected_provider: str | None = None,
    routing_policy: str | None = None,
    fallback_used: bool = False,
    rule_applied: str | None = None,
    error_message: str | None = None,
    usage: dict[str, int] | None = None,
    estimated_cost: float = 0.0,
    cache_hit: bool = False,
) -> None:
    """Persist one RequestLog row (Epic 4.6 + 4.7).

    Deliberately opens its OWN session rather than reusing the calling route's injected
    `db` (apps.gateway.db.session.get_db_session): that session rolls back on any
    exception, including the HTTPException a failed/rejected route raises intentionally
    - which is exactly the request most worth keeping a record of. Also never lets an
    analytics failure break the request it's describing; worst case, one row is lost
    and a warning is logged.
    """

    async def _write() -> None:
        async with db_session_module.async_session_factory() as session:
            log = RequestLog(
                id=uuid.uuid4(),
                request_id=request_id,
                organization_id=uuid.UUID(organization_id) if organization_id else None,
                project_id=uuid.UUID(project_id) if project_id else None,
                requested_model=requested_model,
                selected_provider=selected_provider,
                routing_policy=routing_policy,
                fallback_used=fallback_used,
                rule_applied=rule_applied,
                status=status,
                error_message=error_message,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                estimated_cost=estimated_cost,
                cache_hit=cache_hit,
                latency_ms=timeline.total_ms,
                timeline=timeline.as_dict(),
            )
            session.add(log)
            await session.commit()

    try:
        usage = usage or {}
        await with_lock_retry(_write)
    except Exception as e:
        logger.warning(f"Failed to record analytics for request_id={request_id}: {e}")
        return

    # Webhooks (Epic 5.7): fire-and-forget, after the row is safely committed. A
    # webhook subscriber's outage/slowness must never delay or fail the request this
    # log entry describes.
    event_type = WebhookEvent.REQUEST_COMPLETED if status == "success" else WebhookEvent.REQUEST_FAILED
    fire_and_forget(
        dispatch_webhook_event(
            organization_id,
            event_type,
            {
                "request_id": request_id,
                "requested_model": requested_model,
                "status": status,
                "selected_provider": selected_provider,
                "estimated_cost": estimated_cost,
                "error_message": error_message,
            },
        )
    )
    if status == "success":
        fire_and_forget(check_and_dispatch_quota_exceeded(organization_id))
