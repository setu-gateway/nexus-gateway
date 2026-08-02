import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.auth import DashboardUserContext, Role, require_role, resolve_dashboard_user_or_401
from apps.gateway.db.models import CacheEntry, CachePolicy, Project
from apps.gateway.db.session import get_db_session
from apps.gateway.providers.instance import cache_manager

router = APIRouter(prefix="/cache", tags=["Cache"])


class CachePolicyRequest(BaseModel):
    project_id: str
    enabled: bool = True
    ttl_seconds: int = 3600


class CachePolicyResponse(BaseModel):
    project_id: str | None
    enabled: bool
    ttl_seconds: int


class CacheClearResponse(BaseModel):
    cleared_entries: int


class CacheStatsResponse(BaseModel):
    total_entries: int
    total_hits: int


@router.get("/policy", response_model=CachePolicyResponse)
async def get_cache_policy(
    project_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    _user: DashboardUserContext = Depends(resolve_dashboard_user_or_401),
) -> CachePolicyResponse:
    """Effective cache policy for a project (or the global default if unset/omitted)."""
    policy = await cache_manager.get_policy(project_id, db)
    return CachePolicyResponse(
        project_id=str(policy.project_id) if policy.project_id else None,
        enabled=policy.enabled,
        ttl_seconds=policy.ttl_seconds,
    )


@router.put("/policy", response_model=CachePolicyResponse)
async def set_cache_policy(
    req: CachePolicyRequest,
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_role(Role.ADMIN)),
) -> CachePolicyResponse:
    """Create or update a project's cache policy (Epic 5.1: per-project cache policies)."""
    project_uuid = uuid.UUID(req.project_id)
    project = (await db.execute(select(Project).where(Project.id == project_uuid))).scalar_one_or_none()
    if not project or not user.owns_organization(str(project.organization_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{req.project_id}' not found")

    result = await db.execute(select(CachePolicy).where(CachePolicy.project_id == project_uuid))
    policy = result.scalar_one_or_none()
    if policy:
        policy.enabled = req.enabled
        policy.ttl_seconds = req.ttl_seconds
    else:
        policy = CachePolicy(project_id=project_uuid, enabled=req.enabled, ttl_seconds=req.ttl_seconds)
        db.add(policy)
    await db.flush()
    return CachePolicyResponse(project_id=str(policy.project_id), enabled=policy.enabled, ttl_seconds=policy.ttl_seconds)


@router.get("/stats", response_model=CacheStatsResponse)
async def get_cache_stats(
    db: AsyncSession = Depends(get_db_session), _user: DashboardUserContext = Depends(resolve_dashboard_user_or_401)
) -> CacheStatsResponse:
    """Postgres-tier cache stats (the durable source of truth across all tiers).
    Global across all projects/organizations - this table has no per-tenant split,
    matching the shared cache it's reporting on."""
    result = await db.execute(select(func.count(CacheEntry.id), func.coalesce(func.sum(CacheEntry.hit_count), 0)))
    total_entries, total_hits = result.one()
    return CacheStatsResponse(total_entries=total_entries or 0, total_hits=total_hits or 0)


@router.delete("", response_model=CacheClearResponse)
async def clear_cache(
    project_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    user: DashboardUserContext = Depends(require_role(Role.ADMIN)),
) -> CacheClearResponse:
    """Cache invalidation (Epic 5.1) - backs `setu cache clear`. Omit project_id to
    clear everything across all three tiers - since that affects every tenant's
    cached data, not just the caller's own, it requires Role.OWNER rather than the
    Role.ADMIN a scoped, single-project clear needs."""
    if project_id:
        project = (await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))).scalar_one_or_none()
        if not project or not user.owns_organization(str(project.organization_id)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found")
    elif not user.has_role_at_least(Role.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Clearing the cache for every project requires the 'owner' role")

    cleared = await cache_manager.invalidate(db, project_id=project_id)
    return CacheClearResponse(cleared_entries=cleared)
