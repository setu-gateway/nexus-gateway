from datetime import datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth.api_key import generate_api_key, mask_api_key
from apps.gateway.db.models import APIKey
from apps.gateway.db.session import get_db_session

router = APIRouter(prefix="/keys", tags=["API Keys"])


class ApiKeyCreateRequest(BaseModel):
    project_id: str = Field(description="Associated project UUID")
    name: str = Field(default="Default Key", description="Human readable key label")
    expires_at: Optional[datetime] = Field(default=None, description="Optional key expiration timestamp")


class ApiKeyCreatedResponse(BaseModel):
    id: str
    name: str
    project_id: str
    key: str = Field(description="Plaintext API key - shown ONLY ONCE on creation!")
    masked_key: str
    expires_at: Optional[datetime]
    created_at: datetime


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    project_id: str
    masked_key: str
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime


def _to_response(key: APIKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=str(key.id),
        name=key.name,
        project_id=str(key.project_id),
        masked_key=key.masked_key,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        created_at=key.created_at,
    )


async def _get_active_key_or_404(id: str, db: AsyncSession) -> APIKey:
    try:
        key_id = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API key '{id}' not found")
    result = await db.execute(select(APIKey).where(APIKey.id == key_id, APIKey.revoked_at.is_(None)))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API key '{id}' not found")
    return key


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    req: ApiKeyCreateRequest, db: AsyncSession = Depends(get_db_session)
) -> ApiKeyCreatedResponse:
    """Generate a secure API key (sk_setu_...). Stores ONLY the SHA-256 hash in DB."""
    try:
        project_id = uuid.UUID(req.project_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id must be a valid UUID")

    plaintext_key, hashed_key = generate_api_key(prefix="sk_setu_")
    masked = mask_api_key(plaintext_key)

    key = APIKey(
        id=uuid.uuid4(),
        project_id=project_id,
        name=req.name,
        hashed_key=hashed_key,
        masked_key=masked,
        expires_at=req.expires_at,
    )
    db.add(key)
    await db.flush()

    return ApiKeyCreatedResponse(
        id=str(key.id),
        name=key.name,
        project_id=str(key.project_id),
        key=plaintext_key,
        masked_key=masked,
        expires_at=key.expires_at,
        created_at=key.created_at,
    )


@router.get("", response_model=List[ApiKeyResponse])
async def list_api_keys(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    db: AsyncSession = Depends(get_db_session),
) -> List[ApiKeyResponse]:
    """List active (non-revoked) API keys, masked for safety. Plaintext keys are never returned."""
    query = select(APIKey).where(APIKey.revoked_at.is_(None))
    if project_id:
        try:
            query = query.where(APIKey.project_id == uuid.UUID(project_id))
        except ValueError:
            return []
    result = await db.execute(query)
    return [_to_response(k) for k in result.scalars().all()]


@router.get("/{id}", response_model=ApiKeyResponse)
async def get_api_key(id: str, db: AsyncSession = Depends(get_db_session)) -> ApiKeyResponse:
    """Retrieve API key metadata by ID."""
    key = await _get_active_key_or_404(id, db)
    return _to_response(key)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def revoke_api_key(id: str, db: AsyncSession = Depends(get_db_session)) -> dict:
    """Revoke an API key. Soft-deleted (revoked_at set) rather than removed outright,
    so a compromised-key incident leaves an audit trail (RFC-0008)."""
    key = await _get_active_key_or_404(id, db)
    key.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    return {"message": f"API key '{id}' revoked successfully"}
