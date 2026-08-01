from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from packages.plugin_sdk import ProviderHealthResponse, ProviderPlugin
from packages.shared.logging.logger import get_logger

logger = get_logger("provider_registry")


class ProviderCapabilities(BaseModel):
    chat: bool = True
    embeddings: bool = False
    image: bool = False
    audio: bool = False
    streaming: bool = True
    tools: bool = True
    vision: bool = False


class ProviderMetadata(BaseModel):
    name: str
    provider_name: str
    enabled: bool = True
    capabilities: ProviderCapabilities
    models: List[str] = Field(default_factory=list)


class ProviderRegistry:
    """Registry for managing and executing LLM Provider plugins."""

    def __init__(self):
        self._providers: Dict[str, ProviderPlugin] = {}
        self._enabled_status: Dict[str, bool] = {}
        self._capabilities: Dict[str, ProviderCapabilities] = {}

    def register_provider(
        self,
        provider: ProviderPlugin,
        capabilities: Optional[ProviderCapabilities] = None,
        enabled: bool = True,
    ) -> None:
        """Register a provider plugin instance."""
        name = provider.provider_name.lower()
        self._providers[name] = provider
        self._enabled_status[name] = enabled
        self._capabilities[name] = capabilities or ProviderCapabilities()
        logger.info(f"Registered provider '{name}' (enabled={enabled})")

    def unregister_provider(self, name: str) -> bool:
        """Unregister a provider by name."""
        key = name.lower()
        if key in self._providers:
            del self._providers[key]
            del self._enabled_status[key]
            del self._capabilities[key]
            logger.info(f"Unregistered provider '{key}'")
            return True
        return False

    def enable_provider(self, name: str) -> bool:
        """Enable a registered provider."""
        key = name.lower()
        if key in self._providers:
            self._enabled_status[key] = True
            logger.info(f"Enabled provider '{key}'")
            return True
        return False

    def disable_provider(self, name: str) -> bool:
        """Disable a registered provider."""
        key = name.lower()
        if key in self._providers:
            self._enabled_status[key] = False
            logger.info(f"Disabled provider '{key}'")
            return True
        return False

    def is_enabled(self, name: str) -> bool:
        """Check if provider is enabled."""
        return self._enabled_status.get(name.lower(), False)

    def get_provider(self, name: str) -> Optional[ProviderPlugin]:
        """Get an active, enabled provider instance."""
        key = name.lower()
        if key in self._providers and self._enabled_status.get(key, False):
            return self._providers[key]
        return None

    def get_capabilities(self, name: str) -> Optional[ProviderCapabilities]:
        """Get capability flags for a provider."""
        return self._capabilities.get(name.lower())

    async def list_providers(self) -> List[ProviderMetadata]:
        """List metadata for all registered providers."""
        results: List[ProviderMetadata] = []
        for name, provider in self._providers.items():
            models_list = []
            try:
                models_resp = await provider.models()
                models_list = models_resp.models
            except Exception:
                pass

            results.append(
                ProviderMetadata(
                    name=provider.name,
                    provider_name=name,
                    enabled=self._enabled_status.get(name, False),
                    capabilities=self._capabilities.get(name, ProviderCapabilities()),
                    models=models_list,
                )
            )
        return results

    async def check_all_health(self) -> Dict[str, ProviderHealthResponse]:
        """Query health status across all enabled providers."""
        health_results: Dict[str, ProviderHealthResponse] = {}
        for name, provider in self._providers.items():
            if not self._enabled_status.get(name, False):
                health_results[name] = ProviderHealthResponse(status="offline", latency_ms=None)
                continue
            try:
                health_results[name] = await provider.health()
            except Exception:
                health_results[name] = ProviderHealthResponse(status="offline", latency_ms=None)
        return health_results
