from unittest.mock import MagicMock, patch
import pytest

from packages.plugin_sdk import AudioRequest, ChatRequest, EmbeddingRequest, ImageRequest
from plugins.providers import (
    AnthropicProviderPlugin,
    GeminiProviderPlugin,
    GroqProviderPlugin,
    OllamaProviderPlugin,
    OpenAIProviderPlugin,
)


@pytest.mark.asyncio
async def test_anthropic_provider_all_methods():
    provider = AnthropicProviderPlugin()

    chat_res = await provider.chat(ChatRequest(model="claude-3-5-sonnet", messages=[{"role": "user", "content": "Hi"}]))
    assert "Claude response" in chat_res["choices"][0]["message"]["content"]

    emb_res = await provider.embeddings(EmbeddingRequest(model="claude", input="test"))
    assert "error" in emb_res

    img_res = await provider.image(ImageRequest(prompt="test"))
    assert "error" in img_res

    audio_res = await provider.audio(AudioRequest(file=b"fake"))
    assert "error" in audio_res

    health_res = await provider.health()
    assert health_res.status == "ok"

    models_res = await provider.models()
    assert "claude-3-5-sonnet-20241022" in models_res.models


@pytest.mark.asyncio
async def test_gemini_provider_all_methods():
    provider = GeminiProviderPlugin()

    chat_res = await provider.chat(ChatRequest(model="gemini-1.5-pro", messages=[{"role": "user", "content": "Hi"}]))
    assert "Gemini response" in chat_res["choices"][0]["message"]["content"]

    emb_res = await provider.embeddings(EmbeddingRequest(model="gemini-1.5-pro", input="test"))
    assert len(emb_res["data"][0]["embedding"]) == 3

    img_res = await provider.image(ImageRequest(prompt="test"))
    assert "url" in img_res["data"][0]

    audio_res = await provider.audio(AudioRequest(file=b"fake"))
    assert "text" in audio_res

    health_res = await provider.health()
    assert health_res.status == "ok"

    models_res = await provider.models()
    assert "gemini-1.5-pro" in models_res.models


@pytest.mark.asyncio
async def test_groq_provider_all_methods():
    provider = GroqProviderPlugin()

    chat_res = await provider.chat(ChatRequest(model="groq-llama", messages=[{"role": "user", "content": "Hi"}]))
    assert "Groq LPU response" in chat_res["choices"][0]["message"]["content"]

    emb_res = await provider.embeddings(EmbeddingRequest(model="groq", input="test"))
    assert "error" in emb_res

    img_res = await provider.image(ImageRequest(prompt="test"))
    assert "error" in img_res

    audio_res = await provider.audio(AudioRequest(file=b"fake"))
    assert "text" in audio_res

    health_res = await provider.health()
    assert health_res.status == "ok"

    models_res = await provider.models()
    assert "llama-3.3-70b-versatile" in models_res.models


@pytest.mark.asyncio
async def test_openai_provider_with_api_key_mocking():
    provider = OpenAIProviderPlugin(api_key="sk-mock-key-for-unit-testing")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [{"message": {"role": "assistant", "content": "Mocked OpenAI response"}}],
    })

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        res = await provider.chat(ChatRequest(model="gpt-4o", messages=[{"role": "user", "content": "test"}]))
        assert res["choices"][0]["message"]["content"] == "Mocked OpenAI response"

        emb_res = await provider.embeddings(EmbeddingRequest(model="text-embedding-3-small", input="test"))
        assert emb_res["id"] == "chatcmpl-mock"

        img_res = await provider.image(ImageRequest(prompt="test"))
        assert img_res["id"] == "chatcmpl-mock"


@pytest.mark.asyncio
async def test_ollama_provider_with_http_mocking():
    provider = OllamaProviderPlugin(base_url="http://localhost:11434")

    mock_post_resp = MagicMock()
    mock_post_resp.raise_for_status = MagicMock()
    mock_post_resp.json = MagicMock(return_value={
        "message": {"role": "assistant", "content": "Mocked Ollama response"},
        "done": True,
        "prompt_eval_count": 10,
        "eval_count": 15,
    })

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.raise_for_status = MagicMock()
    mock_get_resp.json = MagicMock(return_value={"models": [{"name": "llama3.2"}, {"name": "mistral"}]})

    with patch("httpx.AsyncClient.post", return_value=mock_post_resp), patch("httpx.AsyncClient.get", return_value=mock_get_resp):
        res = await provider.chat(ChatRequest(model="llama3.2", messages=[{"role": "user", "content": "test"}]))
        assert res["choices"][0]["message"]["content"] == "Mocked Ollama response"
        assert res["usage"]["total_tokens"] == 25

        models_res = await provider.models()
        assert "llama3.2" in models_res.models

        health_res = await provider.health()
        assert health_res.status == "ok"
