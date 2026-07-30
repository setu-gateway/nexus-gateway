import pytest

from packages.plugin_sdk import ChatRequest, EmbeddingRequest
from plugins.providers.ollama.plugin import OllamaProviderPlugin


@pytest.mark.asyncio
async def test_ollama_chat_completion_non_streaming():
    provider = OllamaProviderPlugin()
    req = ChatRequest(model="llama3.2", messages=[{"role": "user", "content": "Hello Ollama"}])

    res = await provider.chat(req)
    assert res["model"] == "llama3.2"
    assert res["object"] == "chat.completion"
    assert len(res["choices"]) > 0


@pytest.mark.asyncio
async def test_ollama_chat_completion_streaming():
    provider = OllamaProviderPlugin()
    req = ChatRequest(model="llama3.2", messages=[{"role": "user", "content": "Stream response"}], stream=True)

    stream_gen = await provider.chat(req)
    chunks = []
    async for chunk in stream_gen:
        chunks.append(chunk)

    assert len(chunks) > 0
    assert any("data: " in c for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_ollama_embeddings():
    provider = OllamaProviderPlugin()
    req = EmbeddingRequest(model="llama3.2", input="Embedding test sentence")

    res = await provider.embeddings(req)
    assert res["model"] == "llama3.2"
    assert len(res["data"][0]["embedding"]) > 0


@pytest.mark.asyncio
async def test_ollama_model_discovery_and_health():
    provider = OllamaProviderPlugin()

    models_resp = await provider.models()
    assert len(models_resp.models) >= 3
    assert "llama3.2" in models_resp.models

    health_resp = await provider.health()
    assert health_resp.status in ("ok", "degraded", "offline")
