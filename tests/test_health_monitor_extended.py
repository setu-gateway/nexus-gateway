import asyncio

import pytest

from apps.gateway.providers import ProviderHealthMonitor, ProviderRegistry
from plugins.providers import OpenAIProviderPlugin


@pytest.mark.asyncio
async def test_health_monitor_background_loop():
    registry = ProviderRegistry()
    openai_p = OpenAIProviderPlugin()
    registry.register_provider(openai_p, enabled=True)

    monitor = ProviderHealthMonitor(registry)

    # Start background monitoring loop
    await monitor.start_background_monitoring(interval_seconds=1)
    assert monitor._is_running is True

    # Sleep briefly to let loop trigger
    await asyncio.sleep(0.1)

    # Stop background monitoring loop
    monitor.stop_background_monitoring()
    assert monitor._is_running is False


@pytest.mark.asyncio
async def test_provider_registry_unregister_and_missing_caps():
    registry = ProviderRegistry()
    openai_p = OpenAIProviderPlugin()

    registry.register_provider(openai_p)
    assert registry.get_capabilities("openai") is not None

    # Unregister provider
    assert registry.unregister_provider("openai") is True
    assert registry.unregister_provider("openai") is False  # Second unregister returns False
    assert registry.get_provider("openai") is None
