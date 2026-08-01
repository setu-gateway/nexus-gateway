from unittest.mock import MagicMock, patch

import httpx
import pytest

from packages.plugin_sdk import ChatRequest, EmbeddingRequest
from plugins.providers.ollama.plugin import OllamaProviderPlugin


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_data)
    return resp


@pytest.mark.asyncio
async def test_ollama_chat_completion_non_streaming():
    provider = OllamaProviderPlugin()
    req = ChatRequest(model="llama3.2", messages=[{"role": "user", "content": "Hello Ollama"}])

    mock_resp = _mock_response(
        {"message": {"role": "assistant", "content": "hi there"}, "done": True, "prompt_eval_count": 5, "eval_count": 3}
    )
    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        res = await provider.chat(req)

    assert res["model"] == "llama3.2"
    assert res["object"] == "chat.completion"
    assert len(res["choices"]) > 0
    assert res["choices"][0]["message"]["content"] == "hi there"


@pytest.mark.asyncio
async def test_ollama_chat_completion_streaming():
    provider = OllamaProviderPlugin()
    req = ChatRequest(model="llama3.2", messages=[{"role": "user", "content": "Stream response"}], stream=True)

    lines = [
        '{"message": {"content": "Hel"}, "done": false}',
        '{"message": {"content": "lo"}, "done": true}',
    ]

    class _FakeStreamResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            for line in lines:
                yield line

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    with patch("httpx.AsyncClient.stream", return_value=_FakeStreamResponse()):
        stream_gen = await provider.chat(req)
        chunks = [chunk async for chunk in stream_gen]

    assert len(chunks) > 0
    assert any("data: " in c for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_ollama_chat_completion_connection_unavailable_uses_mock():
    provider = OllamaProviderPlugin()
    req = ChatRequest(model="llama3.2", messages=[{"role": "user", "content": "Hello Ollama"}])

    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("refused")):
        res = await provider.chat(req)

    assert res["model"] == "llama3.2"
    assert "local response" in res["choices"][0]["message"]["content"].lower()


@pytest.mark.asyncio
async def test_ollama_embeddings():
    provider = OllamaProviderPlugin()
    req = EmbeddingRequest(model="llama3.2", input="Embedding test sentence")

    mock_resp = _mock_response({"embedding": [0.1, 0.2, 0.3]})
    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        res = await provider.embeddings(req)

    assert res["model"] == "llama3.2"
    assert res["data"][0]["embedding"] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_ollama_model_discovery_and_health():
    provider = OllamaProviderPlugin()

    mock_tags = _mock_response({"models": [{"name": "llama3.2"}, {"name": "mistral"}]})
    with patch("httpx.AsyncClient.get", return_value=mock_tags):
        models_resp = await provider.models()
    assert len(models_resp.models) >= 2
    assert "llama3.2" in models_resp.models

    mock_version = _mock_response({"version": "0.1.0"})
    with patch("httpx.AsyncClient.get", return_value=mock_version):
        health_resp = await provider.health()
    assert health_resp.status == "ok"

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("refused")):
        offline_health = await provider.health()
    assert offline_health.status == "offline"
