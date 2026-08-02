import platform
import sys

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from apps.gateway.db.engine import check_database_connection
from apps.gateway.redis.client import check_redis_connection
from packages.shared.config.settings import load_settings

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    components: dict[str, bool]


class ReadinessResponse(BaseModel):
    status: str
    details: dict[str, bool]


class LivenessResponse(BaseModel):
    status: str


class VersionResponse(BaseModel):
    service: str
    version: str
    python_version: str
    platform: str
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health_check(response: Response) -> HealthResponse:
    """Detailed health check endpoint querying downstream dependencies."""
    db_ok = await check_database_connection()
    redis_ok = await check_redis_connection()

    components = {
        "database": db_ok,
        "redis": redis_ok,
    }

    if db_ok and redis_ok:
        system_status = "ok"
    elif db_ok or redis_ok:
        system_status = "degraded"
    else:
        system_status = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    settings = load_settings()
    return HealthResponse(
        status=system_status,
        service=settings.service_name,
        components=components,
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(response: Response) -> ReadinessResponse:
    """Kubernetes readiness probe checking DB and Redis connectivity."""
    db_ok = await check_database_connection()
    redis_ok = await check_redis_connection()

    details = {
        "database": db_ok,
        "redis": redis_ok,
    }

    is_ready = db_ok and redis_ok
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        details=details,
    )


@router.get("/live", response_model=LivenessResponse)
async def liveness_check() -> LivenessResponse:
    """Kubernetes liveness probe indicating application execution."""
    return LivenessResponse(status="alive")


@router.get("/version", response_model=VersionResponse)
async def version_info() -> VersionResponse:
    """Service version and environment details."""
    settings = load_settings()
    return VersionResponse(
        service="setu-gateway",
        version="0.1.0",
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        environment=settings.environment,
    )
