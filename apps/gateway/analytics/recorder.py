from typing import Dict, Optional
import uuid

from apps.gateway.analytics.timeline import RequestTimeline
from apps.gateway.db import session as db_session_module
from apps.gateway.db.models import RequestLog
from packages.shared.logging.logger import get_logger

logger = get_logger("analytics_recorder")


async def record_request(
    *,
    request_id: str,
    requested_model: str,
    status: str,
    timeline: RequestTimeline,
    organization_id: Optional[str] = None,
    selected_provider: Optional[str] = None,
    routing_policy: Optional[str] = None,
    fallback_used: bool = False,
    rule_applied: Optional[str] = None,
    error_message: Optional[str] = None,
    usage: Optional[Dict[str, int]] = None,
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
    try:
        usage = usage or {}
        async with db_session_module.async_session_factory() as session:
            log = RequestLog(
                id=uuid.uuid4(),
                request_id=request_id,
                organization_id=uuid.UUID(organization_id) if organization_id else None,
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
    except Exception as e:
        logger.warning(f"Failed to record analytics for request_id={request_id}: {e}")
