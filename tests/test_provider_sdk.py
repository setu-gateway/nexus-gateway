from typing import Any

import pytest

from packages.plugin_sdk import (
    AudioRequest,
    ChatRequest,
    EmbeddingRequest,
    ImageRequest,
    ProviderHealthResponse,
    ProviderModelResponse,
    ProviderPlugin,
)


class MockProvider(ProviderPlugin):
    name = "mock_provider"
    provider_name = "mock"

    async def chat(self, request: ChatRequest) -> dict[str, Any]:
        return {
            "id": "chatcmpl-mock-123",
            "object": "chat.completion",
            "model": request.model,
            "choices": [{"message": {"role": "assistant", "content": "Mock response"}}],
        }

    async def embeddings(self, request: EmbeddingRequest) -> dict[str, Any]:
        return {
            "object": "list",
            "model": request.model,
            "data": [{"object": "embedding", "embedding": [0.1, 0.2, 0.3], "index": 0}],
        }

    async def image(self, request: ImageRequest) -> dict[str, Any]:
        return {
            "created": 1600000000,
            "data": [{"url": "https://example.com/mock-image.png"}],
        }

    async def audio(self, request: AudioRequest) -> dict[str, Any]:
        return {"text": "Mock audio transcription text"}

    async def health(self) -> ProviderHealthResponse:
        return ProviderHealthResponse(status="ok", latency_ms=12.5)

    async def models(self) -> ProviderModelResponse:
        return ProviderModelResponse(models=["mock-gpt-4o", "mock-embed-v1"])


@pytest.mark.asyncio
async def test_provider_plugin_chat_contract():
    provider = MockProvider()
    req = ChatRequest(model="mock-gpt-4o", messages=[{"role": "user", "content": "Hello"}])

    res = await provider.chat(req)
    assert res["model"] == "mock-gpt-4o"
    assert res["choices"][0]["message"]["content"] == "Mock response"


@pytest.mark.asyncio
async def test_provider_plugin_embeddings_contract():
    provider = MockProvider()
    req = EmbeddingRequest(model="mock-embed-v1", input="Test string")

    res = await provider.embeddings(req)
    assert res["model"] == "mock-embed-v1"
    assert len(res["data"][0]["embedding"]) == 3


@pytest.mark.asyncio
async def test_provider_plugin_image_contract():
    provider = MockProvider()
    req = ImageRequest(prompt="Futuristic city")

    res = await provider.image(req)
    assert res["data"][0]["url"] == "https://example.com/mock-image.png"


@pytest.mark.asyncio
async def test_provider_plugin_audio_contract():
    provider = MockProvider()
    req = AudioRequest(file=b"fake-audio-bytes")

    res = await provider.audio(req)
    assert res["text"] == "Mock audio transcription text"


@pytest.mark.asyncio
async def test_provider_plugin_health_and_models_contract():
    provider = MockProvider()

    health = await provider.health()
    assert health.status == "ok"
    assert health.latency_ms == 12.5

    models_resp = await provider.models()
    assert "mock-gpt-4o" in models_resp.models
