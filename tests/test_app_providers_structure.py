from unittest.mock import MagicMock, patch
import pytest

from apps.gateway.app.providers import (
    BaseProviderPlugin,
    OllamaClient,
    OllamaProviderPlugin,
    OpenAIClient,
    OpenAIProviderPlugin,
    ProviderManager,
    ProviderRegistry,
)
from apps.gateway.providers.health_monitor import ProviderHealthMonitor


@pytest.mark.asyncio
async def test_app_providers_structure_imports_and_manager():
    registry = ProviderRegistry()
    openai_p = OpenAIProviderPlugin()
    registry.register_provider(openai_p, enabled=True)

    monitor = ProviderHealthMonitor(registry)
    manager = ProviderManager(registry, monitor)

    # Provider retrieval via manager
    p = manager.get_provider("openai")
    assert p is openai_p

    # Best provider selection
    best = manager.select_best_provider(["openai", "ollama"])
    assert best is openai_p

    # Enable / Disable operations
    assert manager.disable_provider("openai") is True
    assert manager.get_provider("openai") is None
    assert manager.enable_provider("openai") is True
    assert manager.get_provider("openai") is openai_p


@pytest.mark.asyncio
async def test_openai_and_ollama_clients():
    client_openai = OpenAIClient(api_key="sk-test", base_url="https://api.openai.com/v1")
    client_ollama = OllamaClient(base_url="http://localhost:11434")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"status": "ok"})

    with patch("httpx.AsyncClient.post", return_value=mock_resp), patch("httpx.AsyncClient.get", return_value=mock_resp):
        res_oa = await client_openai.post_chat({"model": "gpt-4o", "messages": []})
        assert res_oa["status"] == "ok"

        res_ol = await client_ollama.post_chat({"model": "llama3.2", "messages": []})
        assert res_ol["status"] == "ok"
