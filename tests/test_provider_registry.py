import pytest

from apps.gateway.providers.registry import ProviderCapabilities, ProviderRegistry
from plugins.providers import (
    AnthropicProviderPlugin,
    GeminiProviderPlugin,
    GroqProviderPlugin,
    OllamaProviderPlugin,
    OpenAIProviderPlugin,
)


@pytest.mark.asyncio
async def test_provider_registry_registration_and_lookup():
    registry = ProviderRegistry()

    openai_p = OpenAIProviderPlugin()
    ollama_p = OllamaProviderPlugin()
    anthropic_p = AnthropicProviderPlugin()
    gemini_p = GeminiProviderPlugin()
    groq_p = GroqProviderPlugin()

    registry.register_provider(openai_p, ProviderCapabilities(chat=True, embeddings=True, image=True, audio=True))
    registry.register_provider(ollama_p, ProviderCapabilities(chat=True, embeddings=True))
    registry.register_provider(anthropic_p, ProviderCapabilities(chat=True))
    registry.register_provider(gemini_p, ProviderCapabilities(chat=True, embeddings=True, image=True, audio=True))
    registry.register_provider(groq_p, ProviderCapabilities(chat=True, audio=True))

    # Lookup enabled providers
    assert registry.get_provider("openai") is openai_p
    assert registry.get_provider("ollama") is ollama_p
    assert registry.get_provider("anthropic") is anthropic_p
    assert registry.get_provider("gemini") is gemini_p
    assert registry.get_provider("groq") is groq_p


@pytest.mark.asyncio
async def test_provider_enable_disable():
    registry = ProviderRegistry()
    openai_p = OpenAIProviderPlugin()
    registry.register_provider(openai_p, enabled=True)

    assert registry.is_enabled("openai") is True
    assert registry.get_provider("openai") is not None

    # Disable provider
    assert registry.disable_provider("openai") is True
    assert registry.is_enabled("openai") is False
    assert registry.get_provider("openai") is None

    # Enable provider back
    assert registry.enable_provider("openai") is True
    assert registry.is_enabled("openai") is True
    assert registry.get_provider("openai") is not None


@pytest.mark.asyncio
async def test_provider_capabilities_and_metadata():
    registry = ProviderRegistry()
    groq_p = GroqProviderPlugin()
    caps = ProviderCapabilities(chat=True, audio=True)
    registry.register_provider(groq_p, capabilities=caps)

    retrieved_caps = registry.get_capabilities("groq")
    assert retrieved_caps is not None
    assert retrieved_caps.chat is True
    assert retrieved_caps.audio is True
    assert retrieved_caps.image is False

    metadata_list = await registry.list_providers()
    assert len(metadata_list) == 1
    assert metadata_list[0].provider_name == "groq"
    assert "llama-3.3-70b-versatile" in metadata_list[0].models


@pytest.mark.asyncio
async def test_provider_registry_health_check():
    registry = ProviderRegistry()
    openai_p = OpenAIProviderPlugin()
    groq_p = GroqProviderPlugin()

    registry.register_provider(openai_p, enabled=True)
    registry.register_provider(groq_p, enabled=False)

    health_map = await registry.check_all_health()
    assert health_map["openai"].status == "ok"
    assert health_map["openai"].latency_ms is not None

    assert health_map["groq"].status == "offline"
    assert health_map["groq"].latency_ms is None
