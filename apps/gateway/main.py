from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.gateway.api.analytics import router as analytics_router
from apps.gateway.api.audit_log import router as audit_log_router
from apps.gateway.api.auth import router as auth_router
from apps.gateway.api.cache import router as cache_router
from apps.gateway.api.comparisons import router as comparisons_router
from apps.gateway.api.evaluation import router as evaluation_router
from apps.gateway.api.health import router as health_router
from apps.gateway.api.keys import router as api_key_router
from apps.gateway.api.mcp import router as mcp_router
from apps.gateway.api.models_api import router as unified_models_router
from apps.gateway.api.openai_v1 import router as openai_v1_router
from apps.gateway.api.optimizer_api import router as optimizer_router
from apps.gateway.api.organizations import router as organization_router
from apps.gateway.api.playground_api import router as playground_router
from apps.gateway.api.policies import router as policies_router
from apps.gateway.api.projects import router as project_router
from apps.gateway.api.prompt_templates import router as prompt_templates_router
from apps.gateway.api.providers_api import router as providers_management_router
from apps.gateway.api.rate_limits import router as rate_limits_router
from apps.gateway.api.routing_rules import router as routing_rules_router
from apps.gateway.api.routing_tools import router as routing_tools_router
from apps.gateway.api.time_machine import router as time_machine_router
from apps.gateway.api.webhooks import router as webhooks_router
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
    title="Setu Gateway",
    description="Enterprise-grade OpenAI-compatible AI Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

# Rejects requests whose Host header isn't in the allowlist (protects against
# Host-header-poisoning attacks on anything that trusts request.url_for()/absolute
# links built from the Host header). settings.allowed_hosts defaults to ["*"], which
# is this middleware's own documented "no restriction" value, so this is a no-op
# until a deployment sets ALLOWED_HOSTS to a real list.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=load_settings().allowed_hosts)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(organization_router)
app.include_router(project_router)
app.include_router(api_key_router)
app.include_router(openai_v1_router)
app.include_router(providers_management_router)
app.include_router(unified_models_router)
app.include_router(playground_router)
app.include_router(routing_rules_router)
app.include_router(routing_tools_router)
app.include_router(analytics_router)
app.include_router(cache_router)
app.include_router(time_machine_router)
app.include_router(rate_limits_router)
app.include_router(webhooks_router)
app.include_router(audit_log_router)
app.include_router(evaluation_router)
app.include_router(prompt_templates_router)
app.include_router(comparisons_router)
app.include_router(mcp_router)
app.include_router(policies_router)
app.include_router(optimizer_router)


def start():
    settings = load_settings()
    # Binding 0.0.0.0 is required inside a container; exposure is bounded by the
    # Docker/K8s port mapping around it, not this bind address.
    uvicorn.run(
        "apps.gateway.main:app",
        host="0.0.0.0",  # nosec B104
        port=settings.port,
        reload=settings.environment == "development",
    )


if __name__ == "__main__":
    start()
