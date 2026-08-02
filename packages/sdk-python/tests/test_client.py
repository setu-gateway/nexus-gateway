import json

import httpx
import pytest
from setu_gateway import AsyncSetuClient, SetuAPIError, SetuClient, SetuConnectionError

_RealClient = httpx.Client
_RealAsyncClient = httpx.AsyncClient


def _transport(*, fail: bool = False, stream: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/chat/completions":
            if fail:
                return httpx.Response(400, json={"detail": "messages is required"})
            payload = json.loads(request.content) if request.content else {}
            if payload.get("stream"):
                sse = (
                    'data: {"choices": [{"delta": {"content": "Hel"}}]}\n\n'
                    'data: {"choices": [{"delta": {"content": "lo"}}]}\n\n'
                    "data: [DONE]\n\n"
                )
                return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "model": payload.get("model", "gpt-4o"),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi there"}}],
                },
            )
        if path == "/v1/embeddings":
            return httpx.Response(200, json={"object": "list", "data": [{"embedding": [0.1, 0.2]}]})
        if path == "/v1/models":
            return httpx.Response(200, json={"object": "list", "data": [{"id": "gpt-4o"}]})
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


def _patch_sync_client(monkeypatch, transport: httpx.MockTransport) -> None:
    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return _RealClient(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


def _patch_async_client(monkeypatch, transport: httpx.MockTransport) -> None:
    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


# --- sync client ---


def test_sync_chat_completions_create(monkeypatch):
    _patch_sync_client(monkeypatch, _transport())
    client = SetuClient(api_key="sk_setu_test", base_url="http://fake")
    resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert resp["choices"][0]["message"]["content"] == "hi there"


def test_sync_chat_completions_sends_bearer_token(monkeypatch):
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_sync_client(monkeypatch, httpx.MockTransport(handler))
    client = SetuClient(api_key="sk_setu_abc123", base_url="http://fake")
    client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert seen_headers["authorization"] == "Bearer sk_setu_abc123"


def test_sync_chat_completions_streaming_parses_sse_chunks(monkeypatch):
    _patch_sync_client(monkeypatch, _transport())
    client = SetuClient(base_url="http://fake")
    chunks = list(client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True))
    content = "".join(c["choices"][0]["delta"]["content"] for c in chunks)
    assert content == "Hello"


def test_sync_embeddings_create(monkeypatch):
    _patch_sync_client(monkeypatch, _transport())
    client = SetuClient(base_url="http://fake")
    resp = client.embeddings.create(model="text-embedding-3-small", input="hello")
    assert resp["data"][0]["embedding"] == [0.1, 0.2]


def test_sync_models_list(monkeypatch):
    _patch_sync_client(monkeypatch, _transport())
    client = SetuClient(base_url="http://fake")
    resp = client.models.list()
    assert resp["data"][0]["id"] == "gpt-4o"


def test_sync_api_error_carries_status_and_body(monkeypatch):
    _patch_sync_client(monkeypatch, _transport(fail=True))
    client = SetuClient(base_url="http://fake")
    with pytest.raises(SetuAPIError) as exc_info:
        client.chat.completions.create(model="gpt-4o", messages=[])
    assert exc_info.value.status_code == 400
    assert "messages is required" in str(exc_info.value)


def test_sync_connection_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patch_sync_client(monkeypatch, httpx.MockTransport(handler))
    client = SetuClient(base_url="http://fake")
    with pytest.raises(SetuConnectionError):
        client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])


def test_client_reads_env_vars(monkeypatch):
    monkeypatch.setenv("SETU_API_KEY", "sk_setu_from_env")
    monkeypatch.setenv("SETU_BASE_URL", "https://env.example.com")
    client = SetuClient()
    assert client.api_key == "sk_setu_from_env"
    assert client.base_url == "https://env.example.com"


def test_client_context_manager_closes(monkeypatch):
    _patch_sync_client(monkeypatch, _transport())
    with SetuClient(base_url="http://fake") as client:
        client.models.list()
    assert client._http.is_closed


# --- async client ---


@pytest.mark.asyncio
async def test_async_chat_completions_create(monkeypatch):
    _patch_async_client(monkeypatch, _transport())
    async with AsyncSetuClient(api_key="sk_setu_test", base_url="http://fake") as client:
        resp = await client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert resp["choices"][0]["message"]["content"] == "hi there"


@pytest.mark.asyncio
async def test_async_chat_completions_streaming(monkeypatch):
    _patch_async_client(monkeypatch, _transport())
    async with AsyncSetuClient(base_url="http://fake") as client:
        stream = await client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True)
        collected = [chunk async for chunk in stream]
    content = "".join(c["choices"][0]["delta"]["content"] for c in collected)
    assert content == "Hello"


@pytest.mark.asyncio
async def test_async_embeddings_create(monkeypatch):
    _patch_async_client(monkeypatch, _transport())
    async with AsyncSetuClient(base_url="http://fake") as client:
        resp = await client.embeddings.create(model="text-embedding-3-small", input="hello")
    assert resp["data"][0]["embedding"] == [0.1, 0.2]


@pytest.mark.asyncio
async def test_async_api_error(monkeypatch):
    _patch_async_client(monkeypatch, _transport(fail=True))
    async with AsyncSetuClient(base_url="http://fake") as client:
        with pytest.raises(SetuAPIError):
            await client.chat.completions.create(model="gpt-4o", messages=[])
