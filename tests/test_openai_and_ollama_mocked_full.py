from unittest.mock import MagicMock, patch
import httpx
import pytest

from packages.plugin_sdk import AudioRequest, ChatRequest, EmbeddingRequest, ImageRequest
from plugins.providers.ollama.plugin import OllamaProviderPlugin
from plugins.providers.openai.plugin import OpenAIProviderPlugin


@pytest.mark.asyncio
async def test_openai_provider_with_api_key_and_mocked_httpx():
    provider = OpenAIProviderPlugin(api_key="sk-real-test-key-12345")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={
        "id": "chatcmpl-123",
        "choices": [{"message": {"role": "assistant", "content": "Mock Response"}}],
        "data": [{"id": "gpt-4o"}, {"id": "text-embedding-3-small"}],
        "text": "Transcribed text sample",
    })

    with patch("httpx.AsyncClient.post", return_value=mock_resp), patch("httpx.AsyncClient.get", return_value=mock_resp):
        chat_res = await provider.chat(ChatRequest(model="gpt-4o", messages=[{"role": "user", "content": "hi"}]))
        assert chat_res["id"] == "chatcmpl-123"

        emb_res = await provider.embeddings(EmbeddingRequest(model="text-embedding-3-small", input="test"))
        assert "data" in emb_res

        img_res = await provider.image(ImageRequest(prompt="test"))
        assert "data" in img_res

        audio_res = await provider.audio(AudioRequest(file=b"fake-audio"))
        assert "text" in audio_res

        health_res = await provider.health()
        assert health_res.status == "ok"

        models_res = await provider.models()
        assert "gpt-4o" in models_res.models


@pytest.mark.asyncio
async def test_openai_provider_health_and_models_error_handling():
    provider = OpenAIProviderPlugin(api_key="sk-real-test-key-12345")

    with patch("httpx.AsyncClient.get", side_effect=RuntimeError("Connection refused")):
        health_res = await provider.health()
        assert health_res.status == "degraded"

        models_res = await provider.models()
        assert "gpt-4o" in models_res.models


@pytest.mark.asyncio
async def test_ollama_provider_full_mocked_calls():
    provider = OllamaProviderPlugin(base_url="http://localhost:11434")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={
        "message": {"role": "assistant", "content": "Ollama Mock Output"},
        "models": [{"name": "llama3.2:latest"}, {"name": "mistral:latest"}],
        "embedding": [0.1, 0.2, 0.3],
        "version": "0.3.0",
    })

    with patch("httpx.AsyncClient.post", return_value=mock_resp), patch("httpx.AsyncClient.get", return_value=mock_resp):
        chat_res = await provider.chat(ChatRequest(model="llama3.2", messages=[{"role": "user", "content": "hi"}]))
        assert chat_res["choices"][0]["message"]["content"] == "Ollama Mock Output"

        emb_res = await provider.embeddings(EmbeddingRequest(model="llama3.2", input="test"))
        assert len(emb_res["data"][0]["embedding"]) == 3

        health_res = await provider.health()
        assert health_res.status == "ok"

        models_res = await provider.models()
        assert "llama3.2:latest" in models_res.models


@pytest.mark.asyncio
async def test_ollama_provider_error_fallbacks():
    provider = OllamaProviderPlugin(base_url="http://localhost:11434")

    mock_err_resp = MagicMock()
    mock_err_resp.status_code = 500
    mock_err_resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("500 Server Error", request=MagicMock(), response=mock_err_resp))

    with patch("httpx.AsyncClient.post", return_value=mock_err_resp), patch("httpx.AsyncClient.get", side_effect=RuntimeError("Ollama offline")):
        chat_res = await provider.chat(ChatRequest(model="llama3.2", messages=[{"role": "user", "content": "hi"}]))
        assert "unreachable" in chat_res["choices"][0]["message"]["content"].lower() or "ollama" in chat_res["choices"][0]["message"]["content"].lower()

        try:
            await provider.embeddings(EmbeddingRequest(model="llama3.2", input="test"))
        except Exception:
            pass

        health_res = await provider.health()
        assert health_res.status in ("degraded", "offline")

        models_res = await provider.models()
        assert len(models_res.models) > 0
