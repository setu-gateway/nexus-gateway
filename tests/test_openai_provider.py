import pytest

from packages.plugin_sdk import AudioRequest, ChatRequest, EmbeddingRequest, ImageRequest
from plugins.providers.openai.plugin import OpenAIProviderPlugin


@pytest.mark.asyncio
async def test_openai_chat_completion_non_streaming():
    provider = OpenAIProviderPlugin()
    req = ChatRequest(model="gpt-4o", messages=[{"role": "user", "content": "Hello OpenAI"}])

    res = await provider.chat(req)
    assert res["model"] == "gpt-4o"
    assert res["choices"][0]["message"]["role"] == "assistant"
    assert "OpenAI Reference Provider response" in res["choices"][0]["message"]["content"]


@pytest.mark.asyncio
async def test_openai_chat_completion_streaming():
    provider = OpenAIProviderPlugin()
    req = ChatRequest(model="gpt-4o", messages=[{"role": "user", "content": "Stream me"}], stream=True)

    stream_gen = await provider.chat(req)
    chunks = []
    async for chunk in stream_gen:
        chunks.append(chunk)

    assert len(chunks) > 0
    assert any("data: " in c for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_openai_embeddings():
    provider = OpenAIProviderPlugin()
    req = EmbeddingRequest(model="text-embedding-3-small", input="Vectorize this sentence")

    res = await provider.embeddings(req)
    assert res["model"] == "text-embedding-3-small"
    assert len(res["data"][0]["embedding"]) == 4


@pytest.mark.asyncio
async def test_openai_models():
    provider = OpenAIProviderPlugin()
    res = await provider.models()

    assert len(res.models) >= 5
    assert "gpt-4o" in res.models
    assert "text-embedding-3-small" in res.models


@pytest.mark.asyncio
async def test_openai_image_and_audio():
    provider = OpenAIProviderPlugin()

    img_req = ImageRequest(prompt="A futuristic AI gateway logo")
    img_res = await provider.image(img_req)
    assert "url" in img_res["data"][0]

    audio_req = AudioRequest(file=b"fake-audio-payload")
    audio_res = await provider.audio(audio_req)
    assert "text" in audio_res


@pytest.mark.asyncio
async def test_openai_health():
    provider = OpenAIProviderPlugin()
    health_resp = await provider.health()

    assert health_resp.status in ("ok", "degraded")
