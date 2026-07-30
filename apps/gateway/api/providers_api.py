from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from apps.gateway.providers.instance import health_monitor, model_registry, provider_registry
from packages.plugin_sdk import ProviderHealthResponse
from packages.shared.config.providers_config import load_providers_config

router = APIRouter(prefix="/providers", tags=["Provider Registry Management"])


class ProviderDetailResponse(BaseModel):
    name: str
    provider_name: str
    enabled: bool
    capabilities: Dict[str, bool]
    models: List[str]


@router.get("", response_model=List[ProviderDetailResponse])
async def list_providers() -> List[ProviderDetailResponse]:
    """List all registered providers, their enabled state, capabilities, and models."""
    providers_meta = await provider_registry.list_providers()
    return [
        ProviderDetailResponse(
            name=p.name,
            provider_name=p.provider_name,
            enabled=p.enabled,
            capabilities=p.capabilities.model_dump(),
            models=p.models,
        )
        for p in providers_meta
    ]


@router.get("/{provider}", response_model=ProviderDetailResponse)
async def get_provider_details(provider: str) -> ProviderDetailResponse:
    """Retrieve metadata and capability details for a specific provider."""
    key = provider.lower()
    prov_instance = provider_registry.get_provider(key)

    # Check if provider exists (even if disabled)
    providers_meta = await provider_registry.list_providers()
    target_meta = next((p for p in providers_meta if p.provider_name == key), None)

    if not target_meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider}' not found in registry",
        )

    return ProviderDetailResponse(
        name=target_meta.name,
        provider_name=target_meta.provider_name,
        enabled=target_meta.enabled,
        capabilities=target_meta.capabilities.model_dump(),
        models=target_meta.models,
    )


@router.get("/{provider}/health", response_model=ProviderHealthResponse)
async def get_provider_health(provider: str) -> ProviderHealthResponse:
    """Check health status and roundtrip ping latency for a specific provider."""
    key = provider.lower()
    prov_instance = provider_registry.get_provider(key)

    if not prov_instance:
        return ProviderHealthResponse(status="offline", latency_ms=None)

    try:
        return await prov_instance.health()
    except Exception:
        return ProviderHealthResponse(status="offline", latency_ms=None)


@router.post("/reload", response_model=Dict[str, Any])
async def reload_providers() -> Dict[str, Any]:
    """Reload provider configuration settings dynamically from environment and configuration overlays."""
    prov_config = load_providers_config()

    for name, setting in prov_config.providers.items():
        if setting.enabled:
            provider_registry.enable_provider(name)
        else:
            provider_registry.disable_provider(name)

    # Trigger health monitor round
    await health_monitor.run_health_check_round()

    active_count = len([p for p in await provider_registry.list_providers() if p.enabled])
    return {
        "message": "Providers reloaded successfully",
        "active_providers_count": active_count,
    }
