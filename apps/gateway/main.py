from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from apps.gateway.api.auth import router as auth_router
from apps.gateway.api.health import router as health_router
from apps.gateway.api.keys import router as api_key_router
from apps.gateway.api.models_api import router as unified_models_router
from apps.gateway.api.openai_v1 import router as openai_v1_router
from apps.gateway.api.organizations import router as organization_router
from apps.gateway.api.playground_api import router as playground_router
from apps.gateway.api.projects import router as project_router
from apps.gateway.api.providers_api import router as providers_management_router
from apps.gateway.redis.client import close_redis_connection
from packages.shared.config.settings import load_settings
from packages.shared.logging.logger import get_logger, setup_structured_logging

logger = get_logger("gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    setup_structured_logging(service_name=settings.service_name, level=settings.log_level)
    logger.info("Initializing Gateway application server", extra={"environment": settings.environment})
    yield
    logger.info("Shutting down Gateway application server")
    await close_redis_connection()


app = FastAPI(
    title="Nexus Gateway",
    description="Enterprise-grade OpenAI-compatible AI Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(organization_router)
app.include_router(project_router)
app.include_router(api_key_router)
app.include_router(openai_v1_router)
app.include_router(providers_management_router)
app.include_router(unified_models_router)
app.include_router(playground_router)


def start():
    settings = load_settings()
    uvicorn.run(
        "apps.gateway.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.environment == "development",
    )


if __name__ == "__main__":
    start()
