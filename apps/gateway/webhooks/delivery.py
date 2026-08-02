import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, select

from apps.gateway.db import session as db_session_module
from apps.gateway.db.models import Organization, RequestLog, WebhookDelivery, WebhookEndpoint
from apps.gateway.db.retry import with_lock_retry
from apps.gateway.utils import fire_and_forget
from apps.gateway.webhooks.events import WebhookEvent
from apps.gateway.webhooks.signing import sign_payload
from packages.shared.logging.logger import get_logger
from packages.shared.network.retry import execute_with_exponential_backoff

logger = get_logger("webhook_delivery")

_DELIVERY_TIMEOUT_SECONDS = 10.0
_MAX_ATTEMPTS = 4
_RESPONSE_BODY_TRUNCATE = 2000


async def dispatch_webhook_event(organization_id: str | None, event_type: str, data: dict[str, Any]) -> None:
    """Fan out `event_type` to every enabled webhook this org has subscribed to it -
    fire-and-forget per endpoint, so one slow/broken receiver never delays the request
    that triggered the event or blocks delivery to the org's other endpoints. Never
    raises: a webhook failure is the receiver's problem, not ours.
    """
    if not organization_id:
        return
    try:
        org_uuid = uuid.UUID(organization_id)
    except ValueError:
        return

    async def _load_endpoints():
        async with db_session_module.async_session_factory() as session:
            result = await session.execute(
                select(WebhookEndpoint).where(WebhookEndpoint.organization_id == org_uuid, WebhookEndpoint.enabled.is_(True))
            )
            return [(e.id, e.url, e.secret, e.event_types) for e in result.scalars().all()]

    try:
        endpoints = await with_lock_retry(_load_endpoints)
    except Exception as e:
        logger.warning(f"Failed to load webhook endpoints for organization_id={organization_id}: {e}")
        return

    for endpoint_id, url, secret, event_types in endpoints:
        if event_types and event_type not in event_types:
            continue
        fire_and_forget(_deliver_to_endpoint(endpoint_id, url, secret, event_type, data))


async def check_and_dispatch_quota_exceeded(organization_id: str | None) -> None:
    """Fires quota.exceeded exactly once per organization per time it crosses its
    monthly_request_quota (Epic 5.6) - triggered on the specific request whose count
    equals quota+1, not on every over-quota request after that, so subscribers get one
    notification per crossing rather than a flood. Tracking/notification only: this
    never blocks the request that triggered it.
    """
    if not organization_id:
        return

    async def _check_quota():
        async with db_session_module.async_session_factory() as session:
            org_result = await session.execute(select(Organization).where(Organization.id == uuid.UUID(organization_id)))
            org = org_result.scalar_one_or_none()
            if not org or org.monthly_request_quota is None:
                return None

            period_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            count_result = await session.execute(
                select(func.count(RequestLog.id)).where(RequestLog.organization_id == org.id, RequestLog.created_at >= period_start)
            )
            requests_used = count_result.scalar_one() or 0
            return requests_used, org.monthly_request_quota

    try:
        quota_check = await with_lock_retry(_check_quota)
    except Exception as e:
        logger.warning(f"Failed to check quota for organization_id={organization_id}: {e}")
        return
    if quota_check is None:
        return
    requests_used, quota = quota_check

    if requests_used == quota + 1:
        await dispatch_webhook_event(
            organization_id,
            WebhookEvent.QUOTA_EXCEEDED,
            {"organization_id": organization_id, "monthly_request_quota": quota, "requests_used": requests_used},
        )


async def _deliver_to_endpoint(endpoint_id: uuid.UUID, url: str, secret: str, event_type: str, data: dict[str, Any]) -> None:
    delivery_id = str(uuid.uuid4())
    body = json.dumps(
        {
            "id": delivery_id,
            "event": event_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        },
        default=str,
    ).encode("utf-8")
    signature = sign_payload(secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-Setu-Event": event_type,
        "X-Setu-Delivery-Id": delivery_id,
        "X-Setu-Signature": f"sha256={signature}",
    }

    attempt_count = 0
    response_status_code: int | None = None
    response_body: str | None = None
    error_message: str | None = None
    status = "failed"

    async def _send() -> None:
        nonlocal attempt_count, response_status_code, response_body
        attempt_count += 1
        async with httpx.AsyncClient(timeout=_DELIVERY_TIMEOUT_SECONDS) as http_client:
            resp = await http_client.post(url, content=body, headers=headers)
        response_status_code = resp.status_code
        response_body = resp.text[:_RESPONSE_BODY_TRUNCATE]
        resp.raise_for_status()

    try:
        await execute_with_exponential_backoff(
            _send, max_retries=_MAX_ATTEMPTS - 1, initial_backoff_sec=1.0, provider_name=f"webhook:{endpoint_id}"
        )
        status = "success"
    except Exception as e:
        error_message = str(e)[:_RESPONSE_BODY_TRUNCATE]

    async def _write() -> None:
        async with db_session_module.async_session_factory() as session:
            session.add(
                WebhookDelivery(
                    id=uuid.uuid4(),
                    webhook_endpoint_id=endpoint_id,
                    event_type=event_type,
                    payload=data,
                    status=status,
                    attempt_count=attempt_count,
                    response_status_code=response_status_code,
                    response_body=response_body,
                    error_message=error_message,
                )
            )
            await session.commit()

    try:
        await with_lock_retry(_write)
    except Exception as e:
        logger.warning(f"Failed to record webhook delivery for endpoint_id={endpoint_id}: {e}")
