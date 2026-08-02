import uuid
from typing import Any

from apps.gateway.db import session as db_session_module
from apps.gateway.db.models import TimeMachineRecord
from apps.gateway.db.retry import with_lock_retry
from packages.shared.logging.logger import get_logger

logger = get_logger("time_machine_recorder")


async def record_time_machine_entry(
    *,
    request_id: str,
    requested_model: str,
    provider: str,
    upstream_model: str,
    request_messages: list[dict[str, Any]],
    request_params: dict[str, Any],
    response_body: dict[str, Any],
    latency_ms: float,
    estimated_cost: float,
    organization_id: str | None = None,
    project_id: str | None = None,
) -> None:
    """Opt-in full capture for Time Machine (Epic 5.2). Opens its own session for the
    same reason apps/gateway/analytics/recorder.py does: streaming callers write this
    after the SSE generator drains, well past the original request-scoped session's
    lifetime. Never raises - a failed capture shouldn't fail the request it's describing.
    """

    async def _write() -> None:
        async with db_session_module.async_session_factory() as session:
            session.add(
                TimeMachineRecord(
                    id=uuid.uuid4(),
                    request_id=request_id,
                    organization_id=uuid.UUID(organization_id) if organization_id else None,
                    project_id=uuid.UUID(project_id) if project_id else None,
                    requested_model=requested_model,
                    provider=provider,
                    upstream_model=upstream_model,
                    request_messages=request_messages,
                    request_params=request_params,
                    response_body=response_body,
                    latency_ms=latency_ms,
                    estimated_cost=estimated_cost,
                )
            )
            await session.commit()

    try:
        await with_lock_retry(_write)
    except Exception as e:
        logger.warning(f"Failed to record Time Machine entry for request_id={request_id}: {e}")
