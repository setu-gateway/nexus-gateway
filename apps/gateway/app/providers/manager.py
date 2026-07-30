from typing import Dict, List, Optional

from apps.gateway.providers.health_monitor import ProviderHealthMetric, ProviderHealthMonitor
from apps.gateway.providers.registry import ProviderRegistry
from packages.provider_sdk import BaseProviderPlugin


class ProviderManager:
    """Manager class coordinating Provider Registry, Health Monitoring, and Model Routing."""

    def __init__(self, registry: ProviderRegistry, health_monitor: ProviderHealthMonitor):
        self.registry = registry
        self.health_monitor = health_monitor

    def get_provider(self, provider_name: str) -> Optional[BaseProviderPlugin]:
        """Get an active, enabled provider instance."""
        return self.registry.get_provider(provider_name)

    def select_best_provider(self, candidates: List[str]) -> Optional[BaseProviderPlugin]:
        """Select the healthiest available provider from candidate names."""
        best_name = self.health_monitor.get_healthiest_provider(candidates)
        if best_name:
            return self.get_provider(best_name)
        return None

    def enable_provider(self, provider_name: str) -> bool:
        return self.registry.enable_provider(provider_name)

    def disable_provider(self, provider_name: str) -> bool:
        return self.registry.disable_provider(provider_name)
