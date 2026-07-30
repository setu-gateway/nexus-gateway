from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from packages.provider_sdk.capabilities import ProviderCapabilities
from packages.provider_sdk.health import ProviderHealthResponse
from packages.provider_sdk.provider import BaseProviderPlugin
from packages.shared.logging.logger import get_logger

logger = get_logger("provider_sdk_registry")


class ProviderInfo(BaseModel):
    """Metadata summary for a registered provider."""

    name: str
    provider_name: str
    enabled: bool = True
    capabilities: ProviderCapabilities
    models: List[str] = Field(default_factory=list)


class ProviderSDKRegistry:
    """Registry engine for managing Provider SDK instances."""

    def __init__(self):
        self._providers: Dict[str, BaseProviderPlugin] = {}
        self._enabled: Dict[str, bool] = {}

    def register(self, provider: BaseProviderPlugin, enabled: bool = True) -> None:
        """Register a provider plugin instance."""
        key = provider.provider_name.lower()
        self._providers[key] = provider
        self._enabled[key] = enabled
        logger.info(f"Provider '{key}' registered in SDK registry (enabled={enabled})")

    def unregister(self, provider_name: str) -> bool:
        """Unregister a provider by name."""
        key = provider_name.lower()
        if key in self._providers:
            del self._providers[key]
            del self._enabled[key]
            return True
        return False

    def get(self, provider_name: str) -> Optional[BaseProviderPlugin]:
        """Get an active, enabled provider instance."""
        key = provider_name.lower()
        if key in self._providers and self._enabled.get(key, False):
            return self._providers[key]
        return None

    def enable(self, provider_name: str) -> bool:
        """Enable a provider."""
        key = provider_name.lower()
        if key in self._providers:
            self._enabled[key] = True
            return True
        return False

    def disable(self, provider_name: str) -> bool:
        """Disable a provider."""
        key = provider_name.lower()
        if key in self._providers:
            self._enabled[key] = False
            return True
        return False

    async def list_info(self) -> List[ProviderInfo]:
        """List provider metadata info across registered adapters."""
        res: List[ProviderInfo] = []
        for name, provider in self._providers.items():
            models_list = []
            try:
                m_resp = await provider.models()
                models_list = m_resp.models
            except Exception:
                pass

            res.append(
                ProviderInfo(
                    name=provider.name,
                    provider_name=name,
                    enabled=self._enabled.get(name, False),
                    capabilities=provider.capabilities(),
                    models=models_list,
                )
            )
        return res
