from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth.api_key import hash_api_key
from apps.gateway.db.models import APIKey, Project


@dataclass
class RequestAuthContext:
    api_key_id: str
    project_id: str
    organization_id: str


async def resolve_api_key(db: AsyncSession, authorization_header: Optional[str]) -> Optional[RequestAuthContext]:
    """Resolve a Bearer API key to its owning project/organization (RFC-0007: scoped
    API keys as the tenant-resolution mechanism). Returns None if no key was
    presented, or the key is missing/revoked/expired - callers decide whether that's
    acceptable. These endpoints don't *require* auth yet (see apps/gateway/api/openai_v1.py):
    making it mandatory is a bigger, separate decision that would break the current
    playground/quickstart/test flows, which all call the API unauthenticated today.
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None

    plaintext_key = authorization_header.split(" ", 1)[1].strip()
    if not plaintext_key:
        return None

    hashed = hash_api_key(plaintext_key)
    result = await db.execute(select(APIKey).where(APIKey.hashed_key == hashed))
    key = result.scalar_one_or_none()

    if not key or key.revoked_at is not None:
        return None
    if key.expires_at is not None and key.expires_at < datetime.now(timezone.utc):
        return None

    project_result = await db.execute(select(Project).where(Project.id == key.project_id))
    project = project_result.scalar_one_or_none()
    if not project:
        return None

    key.last_used_at = datetime.now(timezone.utc)

    return RequestAuthContext(
        api_key_id=str(key.id),
        project_id=str(key.project_id),
        organization_id=str(project.organization_id),
    )
