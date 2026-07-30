from typing import AsyncGenerator, Dict, Any
import pytest

from packages.provider_sdk import (
    BaseProviderPlugin,
    ChatRequest,
    EmbeddingRequest,
    ProviderAuthenticationError,
    ProviderCapabilities,
    ProviderException,
    ProviderHealthResponse,
    ProviderModelResponse,
    ProviderRateLimitError,
    ProviderSDKRegistry,
)


class SampleSDKProvider(BaseProviderPlugin):
    name = "Sample Provider"
    provider_name = "sample"

    async def chat(self, request: ChatRequest) -> Any:
        return {"choices": [{"message": {"content": "Sample response"}}]}

    async def stream(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        yield "data: {\"choices\": [{\"delta\": {\"content\": \"Sample\"}}]}\n\n"
        yield "data: [DONE]\n\n"

    async def embeddings(self, request: EmbeddingRequest) -> Dict[str, Any]:
        return {"data": [{"embedding": [0.1, 0.2]}]}

    async def models(self) -> ProviderModelResponse:
        return ProviderModelResponse(models=["sample-model-v1"])

    async def health(self) -> ProviderHealthResponse:
        return ProviderHealthResponse(status="ok", latency_ms=5.0)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(chat=True, embeddings=True, streaming=True)


@pytest.mark.asyncio
async def test_provider_sdk_base_interface():
    provider = SampleSDKProvider()

    chat_res = await provider.chat(ChatRequest(model="sample-model-v1", messages=[{"role": "user", "content": "Hi"}]))
    assert chat_res["choices"][0]["message"]["content"] == "Sample response"

    chunks = []
    async for chunk in provider.stream(ChatRequest(model="sample-model-v1", messages=[])):
        chunks.append(chunk)
    assert len(chunks) == 2
    assert chunks[-1] == "data: [DONE]\n\n"

    emb_res = await provider.embeddings(EmbeddingRequest(model="sample-model-v1", input="test"))
    assert len(emb_res["data"][0]["embedding"]) == 2

    health = await provider.health()
    assert health.status == "ok"
    assert health.latency_ms == 5.0

    caps = provider.capabilities()
    assert caps.chat is True
    assert caps.embeddings is True
    assert caps.streaming is True


def test_provider_exceptions():
    base_exc = ProviderException("General error", provider_name="sample", status_code=500)
    assert base_exc.status_code == 500
    assert base_exc.provider_name == "sample"

    auth_exc = ProviderAuthenticationError("Bad Key", provider_name="openai")
    assert auth_exc.status_code == 401

    rate_exc = ProviderRateLimitError("Too Many Requests", provider_name="groq")
    assert rate_exc.status_code == 429


@pytest.mark.asyncio
async def test_provider_sdk_registry_operations():
    registry = ProviderSDKRegistry()
    provider = SampleSDKProvider()

    registry.register(provider, enabled=True)
    assert registry.get("sample") is provider

    # Disable provider
    registry.disable("sample")
    assert registry.get("sample") is None

    # Enable provider
    registry.enable("sample")
    assert registry.get("sample") is provider

    info_list = await registry.list_info()
    assert len(info_list) == 1
    assert info_list[0].provider_name == "sample"
    assert "sample-model-v1" in info_list[0].models

    # Unregister provider
    assert registry.unregister("sample") is True
    assert registry.get("sample") is None
