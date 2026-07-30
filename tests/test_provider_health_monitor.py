import pytest

from apps.gateway.providers import ProviderHealthMonitor, ProviderRegistry
from plugins.providers import OpenAIProviderPlugin, OllamaProviderPlugin, GroqProviderPlugin


@pytest.mark.asyncio
async def test_provider_health_monitor_metrics_recording():
    registry = ProviderRegistry()
    monitor = ProviderHealthMonitor(registry)

    openai_p = OpenAIProviderPlugin()
    registry.register_provider(openai_p, enabled=True)

    # 1. Record 4 successful requests
    for _ in range(4):
        monitor.record_request_result("openai", success=True, latency_ms=20.0)

    metric = monitor.get_metrics("openai")
    assert metric.total_requests == 4
    assert metric.total_errors == 0
    assert metric.error_rate == 0.0
    assert metric.availability_score == 100.0
    assert metric.status == "online"

    # 2. Record rate limit event
    monitor.record_request_result("openai", success=False, latency_ms=100.0, is_rate_limit=True)
    metric_after_rl = monitor.get_metrics("openai")
    assert metric_after_rl.is_rate_limited is True
    assert metric_after_rl.status == "degraded"


@pytest.mark.asyncio
async def test_provider_health_monitor_polling():
    registry = ProviderRegistry()
    openai_p = OpenAIProviderPlugin()
    ollama_p = OllamaProviderPlugin()

    registry.register_provider(openai_p, enabled=True)
    registry.register_provider(ollama_p, enabled=True)

    monitor = ProviderHealthMonitor(registry)
    results = await monitor.run_health_check_round()

    assert "openai" in results
    assert "ollama" in results
    assert results["openai"].status in ("online", "degraded")


@pytest.mark.asyncio
async def test_healthiest_provider_selection():
    registry = ProviderRegistry()
    openai_p = OpenAIProviderPlugin()
    groq_p = GroqProviderPlugin()

    registry.register_provider(openai_p, enabled=True)
    registry.register_provider(groq_p, enabled=True)

    monitor = ProviderHealthMonitor(registry)

    # Record higher error rate for OpenAI
    for _ in range(5):
        monitor.record_request_result("openai", success=False, latency_ms=200.0)

    # Record fast, error-free results for Groq
    for _ in range(5):
        monitor.record_request_result("groq", success=True, latency_ms=5.0)

    best = monitor.get_healthiest_provider(["openai", "groq"])
    assert best == "groq"
