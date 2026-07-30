from datetime import datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from apps.gateway.auth.api_key import generate_api_key, mask_api_key

router = APIRouter(prefix="/keys", tags=["API Keys"])

# In-memory store stub (syncs with Database models in full execution)
_api_keys_db_stub: dict[str, dict] = {}


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


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(req: ApiKeyCreateRequest) -> ApiKeyCreatedResponse:
    """Generate a secure API key (sk_setu_...). Stores ONLY the SHA-256 hash in DB."""
    key_id = str(uuid.uuid4())
    plaintext_key, hashed_key = generate_api_key(prefix="sk_setu_")
    masked = mask_api_key(plaintext_key)
    now = datetime.now(timezone.utc)

    key_record = {
        "id": key_id,
        "name": req.name,
        "project_id": req.project_id,
        "hashed_key": hashed_key,
        "masked_key": masked,
        "last_used_at": None,
        "expires_at": req.expires_at,
        "created_at": now,
    }

    _api_keys_db_stub[key_id] = key_record

    return ApiKeyCreatedResponse(
        id=key_id,
        name=req.name,
        project_id=req.project_id,
        key=plaintext_key,
        masked_key=masked,
        expires_at=req.expires_at,
        created_at=now,
    )


@router.get("", response_model=List[ApiKeyResponse])
async def list_api_keys(
    project_id: Optional[str] = Query(None, description="Filter by project ID")
) -> List[ApiKeyResponse]:
    """List API keys (masked for safety). Plaintext keys are never returned."""
    keys = list(_api_keys_db_stub.values())
    if project_id:
        keys = [k for k in keys if k["project_id"] == project_id]
    return [ApiKeyResponse(**k) for k in keys]


@router.get("/{id}", response_model=ApiKeyResponse)
async def get_api_key(id: str) -> ApiKeyResponse:
    """Retrieve API key metadata by ID."""
    key = _api_keys_db_stub.get(id)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{id}' not found",
        )
    return ApiKeyResponse(**key)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def revoke_api_key(id: str) -> dict:
    """Revoke/delete an API key by ID."""
    key = _api_keys_db_stub.pop(id, None)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{id}' not found",
        )
    return {"message": f"API key '{id}' revoked successfully"}
