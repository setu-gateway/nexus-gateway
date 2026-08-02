import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth import DashboardUserContext, Permission, require_permission, resolve_dashboard_user_or_401
from apps.gateway.db.models import WebhookDelivery, WebhookEndpoint
from apps.gateway.db.session import get_db_session
from apps.gateway.webhooks.events import WebhookEvent
from apps.gateway.webhooks.signing import generate_webhook_secret

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


class WebhookEndpointCreateRequest(BaseModel):
    organization_id: str = Field(description="Owning organization UUID")
    url: str = Field(description="HTTPS URL events are POSTed to")
    description: str | None = Field(default=None, max_length=255)
    event_types: list[str] | None = Field(default=None, description="Subscribed events. Omit for all events.")
    enabled: bool = Field(default=True)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not v.startswith("https://") and not v.startswith("http://"):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("event_types")
    @classmethod
    def _validate_event_types(cls, v: list[str] | None) -> list[str] | None:
        if not v:
            return v
        unknown = set(v) - WebhookEvent.ALL
        if unknown:
            raise ValueError(f"Unknown event type(s): {', '.join(sorted(unknown))}. Valid: {', '.join(sorted(WebhookEvent.ALL))}")
        return v


class WebhookEndpointUpdateRequest(BaseModel):
    url: str | None = None
    description: str | None = Field(default=None, max_length=255)
    event_types: list[str] | None = None
    enabled: bool | None = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://") and not v.startswith("http://"):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("event_types")
    @classmethod
    def _validate_event_types(cls, v: list[str] | None) -> list[str] | None:
        if not v:
            return v
        unknown = set(v) - WebhookEvent.ALL
        if unknown:
            raise ValueError(f"Unknown event type(s): {', '.join(sorted(unknown))}. Valid: {', '.join(sorted(WebhookEvent.ALL))}")
        return v


class WebhookEndpointResponse(BaseModel):
    id: str
    organization_id: str
    url: str
    description: str | None
    event_types: list[str] | None
    enabled: bool
    secret_rotated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WebhookEndpointCreatedResponse(WebhookEndpointResponse):
    secret: str = Field(description="Signing secret - shown ONLY ONCE on creation/rotation!")


class WebhookDeliveryResponse(BaseModel):
    id: str
    webhook_endpoint_id: str
    event_type: str
    payload: dict[str, Any]
    status: str
    attempt_count: int
    response_status_code: int | None
    response_body: str | None
    error_message: str | None
    created_at: datetime


def _to_response(endpoint: WebhookEndpoint) -> WebhookEndpointResponse:
    return WebhookEndpointResponse(
        id=str(endpoint.id),
        organization_id=str(endpoint.organization_id),
        url=endpoint.url,
        description=endpoint.description,
        event_types=endpoint.event_types,
        enabled=endpoint.enabled,
        secret_rotated_at=endpoint.secret_rotated_at,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


def _delivery_to_response(delivery: WebhookDelivery) -> WebhookDeliveryResponse:
    return WebhookDeliveryResponse(
        id=str(delivery.id),
        webhook_endpoint_id=str(delivery.webhook_endpoint_id),
        event_type=delivery.event_type,
        payload=delivery.payload,
        status=delivery.status,
        attempt_count=delivery.attempt_count,
        response_status_code=delivery.response_status_code,
        response_body=delivery.response_body,
        error_message=delivery.error_message,
        created_at=delivery.created_at,
    )


async def _get_endpoint_or_404(id: str, db: AsyncSession, user: DashboardUserContext) -> WebhookEndpoint:
    try:
        endpoint_id = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Webhook endpoint '{id}' not found") from None
    result = await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id))
    endpoint = result.scalar_one_or_none()
    if not endpoint or not user.owns_organization(str(endpoint.organization_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Webhook endpoint '{id}' not found")
    return endpoint


@router.post("", response_model=WebhookEndpointCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook_endpoint(
    req: WebhookEndpointCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> WebhookEndpointCreatedResponse:
    if not user.owns_organization(req.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create a webhook for another organization")
    try:
        org_id = uuid.UUID(req.organization_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id must be a valid UUID") from None

    secret = generate_webhook_secret()
    endpoint = WebhookEndpoint(
        id=uuid.uuid4(),
        organization_id=org_id,
        url=req.url,
        secret=secret,
        description=req.description,
        event_types=req.event_types,
        enabled=req.enabled,
    )
    db.add(endpoint)
    await db.flush()
    return WebhookEndpointCreatedResponse(**_to_response(endpoint).model_dump(), secret=secret)


@router.get("", response_model=list[WebhookEndpointResponse])
async def list_webhook_endpoints(
    organization_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[WebhookEndpointResponse]:
    if organization_id and not user.owns_organization(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot list webhooks for another organization")
    query = select(WebhookEndpoint)
    if user.organization_id:
        query = query.where(WebhookEndpoint.organization_id == uuid.UUID(user.organization_id))
    else:
        return []
    result = await db.execute(query.order_by(WebhookEndpoint.created_at.desc()))
    return [_to_response(e) for e in result.scalars().all()]


@router.get("/{id}", response_model=WebhookEndpointResponse)
async def get_webhook_endpoint(
    id: str, db: AsyncSession = Depends(get_db_session), user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> WebhookEndpointResponse:
    return _to_response(await _get_endpoint_or_404(id, db, user))


@router.patch("/{id}", response_model=WebhookEndpointResponse)
async def update_webhook_endpoint(
    id: str,
    req: WebhookEndpointUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> WebhookEndpointResponse:
    endpoint = await _get_endpoint_or_404(id, db, user)
    if req.url is not None:
        endpoint.url = req.url
    if req.description is not None:
        endpoint.description = req.description
    if req.event_types is not None:
        endpoint.event_types = req.event_types
    if req.enabled is not None:
        endpoint.enabled = req.enabled
    await db.flush()
    return _to_response(endpoint)


@router.post("/{id}/rotate-secret", response_model=WebhookEndpointCreatedResponse)
async def rotate_webhook_secret(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> WebhookEndpointCreatedResponse:
    """Issue a new signing secret, invalidating the old one immediately - for a
    suspected leak or routine rotation. The old secret is not retained anywhere."""
    endpoint = await _get_endpoint_or_404(id, db, user)
    new_secret = generate_webhook_secret()
    endpoint.secret = new_secret
    endpoint.secret_rotated_at = datetime.now(timezone.utc)
    await db.flush()
    return WebhookEndpointCreatedResponse(**_to_response(endpoint).model_dump(), secret=new_secret)


@router.get("/{id}/deliveries", response_model=list[WebhookDeliveryResponse])
async def list_webhook_deliveries(
    id: str,
    status_filter: str | None = Query(default=None, alias="status", description="'success' or 'failed'"),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> list[WebhookDeliveryResponse]:
    endpoint = await _get_endpoint_or_404(id, db, user)
    query = select(WebhookDelivery).where(WebhookDelivery.webhook_endpoint_id == endpoint.id)
    if status_filter:
        query = query.where(WebhookDelivery.status == status_filter)
    query = query.order_by(WebhookDelivery.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return [_delivery_to_response(d) for d in result.scalars().all()]


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_webhook_endpoint(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> dict:
    endpoint = await _get_endpoint_or_404(id, db, user)
    await db.delete(endpoint)
    await db.flush()
    return {"message": f"Webhook endpoint '{id}' deleted successfully"}
