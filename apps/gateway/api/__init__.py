from apps.gateway.api.auth import router as auth_router
from apps.gateway.api.health import router as health_router
from apps.gateway.api.keys import router as api_key_router
from apps.gateway.api.models_api import router as unified_models_router
from apps.gateway.api.openai_v1 import router as openai_v1_router
from apps.gateway.api.organizations import router as organization_router
from apps.gateway.api.playground_api import router as playground_router
from apps.gateway.api.projects import router as project_router
from apps.gateway.api.providers_api import router as providers_management_router

__all__ = [
    "health_router",
    "auth_router",
    "organization_router",
    "project_router",
    "api_key_router",
    "openai_v1_router",
    "providers_management_router",
    "unified_models_router",
    "playground_router",
]
