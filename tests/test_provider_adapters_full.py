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
    mock_resp.json = MagicMock(
        return_value={
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "model": "gpt-4o",
            "choices": [{"message": {"role": "assistant", "content": "Mocked OpenAI response"}}],
        }
    )

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
    mock_post_resp.json = MagicMock(
        return_value={
            "message": {"role": "assistant", "content": "Mocked Ollama response"},
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 15,
        }
    )

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


@pytest.mark.asyncio
async def test_anthropic_provider_with_api_key_calls_real_messages_api():
    """With a key configured, chat() must call the real Messages API (not the mock
    fallback) and correctly translate Anthropic's response shape - system prompt
    extracted from messages into a top-level field, content blocks joined into text,
    stop_reason mapped to OpenAI's finish_reason vocabulary."""
    provider = AnthropicProviderPlugin(api_key="sk-ant-mock-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(
        return_value={
            "id": "msg_mock123",
            "model": "claude-3-5-sonnet-20241022",
            "content": [{"type": "text", "text": "Hello from real Claude"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 12, "output_tokens": 6},
        }
    )

    captured = {}

    async def _fake_post(self, url, json=None, headers=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return mock_resp

    with patch("httpx.AsyncClient.post", new=_fake_post):
        res = await provider.chat(
            ChatRequest(
                model="claude-3-5-sonnet",
                messages=[{"role": "system", "content": "Be terse."}, {"role": "user", "content": "Hi"}],
            )
        )

    assert res["choices"][0]["message"]["content"] == "Hello from real Claude"
    assert res["choices"][0]["finish_reason"] == "stop"
    assert res["usage"] == {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18}
    # system role message must not be forwarded as a message - Anthropic rejects that
    assert all(m["role"] != "system" for m in captured["json"]["messages"])
    assert captured["json"]["system"] == "Be terse."
    assert captured["json"]["max_tokens"] > 0  # required by Anthropic; must have a default
    assert captured["headers"]["x-api-key"] == "sk-ant-mock-key"
    assert captured["url"].endswith("/messages")


@pytest.mark.asyncio
async def test_anthropic_provider_without_api_key_uses_mock():
    provider = AnthropicProviderPlugin(api_key=None)
    with patch("httpx.AsyncClient.post") as mock_post:
        res = await provider.chat(ChatRequest(model="claude-3-5-sonnet", messages=[{"role": "user", "content": "hi"}]))
    mock_post.assert_not_called()
    assert "Claude response" in res["choices"][0]["message"]["content"]


@pytest.mark.asyncio
async def test_gemini_provider_with_api_key_calls_real_generatecontent_api():
    """With a key configured, chat() must call the real generateContent API and
    translate Gemini's candidates/usageMetadata shape - including mapping the
    "assistant" role to Gemini's "model" role and extracting system messages into
    systemInstruction rather than sending them as a content entry."""
    provider = GeminiProviderPlugin(api_key="AIzaMockKey")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(
        return_value={
            "candidates": [{"content": {"parts": [{"text": "Hello from real Gemini"}], "role": "model"}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 5, "totalTokenCount": 14},
        }
    )

    captured = {}

    async def _fake_post(self, url, params=None, json=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        captured["json"] = json
        return mock_resp

    with patch("httpx.AsyncClient.post", new=_fake_post):
        res = await provider.chat(
            ChatRequest(
                model="gemini-1.5-pro",
                messages=[
                    {"role": "system", "content": "Be terse."},
                    {"role": "user", "content": "Hi"},
                    {"role": "assistant", "content": "Hello!"},
                ],
            )
        )

    assert res["choices"][0]["message"]["content"] == "Hello from real Gemini"
    assert res["choices"][0]["finish_reason"] == "stop"
    assert res["usage"] == {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14}
    assert captured["params"]["key"] == "AIzaMockKey"
    assert captured["json"]["systemInstruction"]["parts"][0]["text"] == "Be terse."
    roles = [c["role"] for c in captured["json"]["contents"]]
    assert roles == ["user", "model"]  # "assistant" translated to Gemini's "model"
    assert captured["url"].endswith("gemini-1.5-pro:generateContent")


@pytest.mark.asyncio
async def test_gemini_provider_without_api_key_uses_mock():
    provider = GeminiProviderPlugin(api_key=None)
    with patch("httpx.AsyncClient.post") as mock_post:
        res = await provider.chat(ChatRequest(model="gemini-1.5-pro", messages=[{"role": "user", "content": "hi"}]))
    mock_post.assert_not_called()
    assert "Gemini response" in res["choices"][0]["message"]["content"]


@pytest.mark.asyncio
async def test_groq_provider_with_api_key_calls_real_openai_compatible_api():
    """Groq's API is OpenAI-wire-compatible, so this should behave like
    OpenAIProviderPlugin: a near-passthrough call with a Bearer token."""
    provider = GroqProviderPlugin(api_key="gsk-mock-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(
        return_value={
            "id": "chatcmpl-real-groq",
            "object": "chat.completion",
            "model": "llama-3.3-70b-versatile",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello from real Groq"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11},
        }
    )

    captured = {}

    async def _fake_post(self, url, json=None, headers=None, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        return mock_resp

    with patch("httpx.AsyncClient.post", new=_fake_post):
        res = await provider.chat(ChatRequest(model="groq-llama-3.3", messages=[{"role": "user", "content": "hi"}]))

    assert res["choices"][0]["message"]["content"] == "Hello from real Groq"
    assert captured["headers"]["Authorization"] == "Bearer gsk-mock-key"
    assert captured["url"].endswith("/chat/completions")


@pytest.mark.asyncio
async def test_groq_provider_without_api_key_uses_mock():
    provider = GroqProviderPlugin(api_key=None)
    with patch("httpx.AsyncClient.post") as mock_post:
        res = await provider.chat(ChatRequest(model="groq-llama-3.3", messages=[{"role": "user", "content": "hi"}]))
    mock_post.assert_not_called()
    assert "Groq LPU response" in res["choices"][0]["message"]["content"]
