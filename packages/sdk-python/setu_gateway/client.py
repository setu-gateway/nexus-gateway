import json
import os
from collections.abc import Iterator
from typing import Any

import httpx

from setu_gateway.errors import SetuAPIError, SetuConnectionError

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 60.0


def _resolve_base_url(base_url: str | None) -> str:
    return (base_url or os.environ.get("SETU_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def _resolve_api_key(api_key: str | None) -> str | None:
    return api_key or os.environ.get("SETU_API_KEY")


def _auth_headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        body = resp.json()
        message = body.get("detail", resp.text)
    except ValueError:
        body = resp.text
        message = body
    raise SetuAPIError(f"Setu Gateway request failed ({resp.status_code}): {message}", status_code=resp.status_code, body=body)


def _parse_sse_line(line: str) -> dict[str, Any] | None:
    """One "data: {...}" SSE line -> its parsed JSON payload, or None for a blank
    line, a non-data line, or the terminal "[DONE]" sentinel."""
    if not line.startswith("data: "):
        return None
    payload = line[len("data: ") :].strip()
    if payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


class _ChatCompletions:
    def __init__(self, client: "SetuClient"):
        self._client = client

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        stream: bool = False,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        stop: str | list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        payload = _build_chat_payload(model, messages, stream, temperature, top_p, max_tokens, stop, extra)
        if stream:
            return self._client._stream("POST", "/v1/chat/completions", json=payload)
        return self._client._request("POST", "/v1/chat/completions", json=payload)


class _AsyncChatCompletions:
    def __init__(self, client: "AsyncSetuClient"):
        self._client = client

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        stream: bool = False,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        stop: str | list[str] | None = None,
        **extra: Any,
    ):
        payload = _build_chat_payload(model, messages, stream, temperature, top_p, max_tokens, stop, extra)
        if stream:
            return self._client._stream("POST", "/v1/chat/completions", json=payload)
        return await self._client._request("POST", "/v1/chat/completions", json=payload)


def _build_chat_payload(model, messages, stream, temperature, top_p, max_tokens, stop, extra) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if stop is not None:
        payload["stop"] = stop
    payload.update(extra)
    return payload


class _Chat:
    def __init__(self, client: "SetuClient"):
        self.completions = _ChatCompletions(client)


class _AsyncChat:
    def __init__(self, client: "AsyncSetuClient"):
        self.completions = _AsyncChatCompletions(client)


class _Embeddings:
    def __init__(self, client: "SetuClient"):
        self._client = client

    def create(self, *, model: str, input: str | list[str], **extra: Any) -> dict[str, Any]:
        payload = {"model": model, "input": input, **extra}
        return self._client._request("POST", "/v1/embeddings", json=payload)


class _AsyncEmbeddings:
    def __init__(self, client: "AsyncSetuClient"):
        self._client = client

    async def create(self, *, model: str, input: str | list[str], **extra: Any) -> dict[str, Any]:
        payload = {"model": model, "input": input, **extra}
        return await self._client._request("POST", "/v1/embeddings", json=payload)


class _Models:
    def __init__(self, client: "SetuClient"):
        self._client = client

    def list(self) -> dict[str, Any]:
        return self._client._request("GET", "/v1/models")


class _AsyncModels:
    def __init__(self, client: "AsyncSetuClient"):
        self._client = client

    async def list(self) -> dict[str, Any]:
        return await self._client._request("GET", "/v1/models")


class SetuClient:
    """Synchronous client for the Setu Gateway's OpenAI-compatible API.

    >>> client = SetuClient(api_key="sk_setu_...", base_url="https://gateway.example.com")
    >>> client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_key = _resolve_api_key(api_key)
        self.base_url = _resolve_base_url(base_url)
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, headers=_auth_headers(self.api_key))

        self.chat = _Chat(self)
        self.embeddings = _Embeddings(self)
        self.models = _Models(self)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.ConnectError as e:
            raise SetuConnectionError(f"Could not reach Setu Gateway at {self.base_url}: {e}") from e
        _raise_for_status(resp)
        return resp.json()

    def _stream(self, method: str, path: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        try:
            with self._http.stream(method, path, **kwargs) as resp:
                _raise_for_status(resp)
                for line in resp.iter_lines():
                    chunk = _parse_sse_line(line)
                    if chunk is not None:
                        yield chunk
        except httpx.ConnectError as e:
            raise SetuConnectionError(f"Could not reach Setu Gateway at {self.base_url}: {e}") from e

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "SetuClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


class AsyncSetuClient:
    """Asynchronous client for the Setu Gateway's OpenAI-compatible API.

    >>> async with AsyncSetuClient(api_key="sk_setu_...") as client:
    ...     await client.chat.completions.create(model="gpt-4o", messages=[...])
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_key = _resolve_api_key(api_key)
        self.base_url = _resolve_base_url(base_url)
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, headers=_auth_headers(self.api_key))

        self.chat = _AsyncChat(self)
        self.embeddings = _AsyncEmbeddings(self)
        self.models = _AsyncModels(self)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = await self._http.request(method, path, **kwargs)
        except httpx.ConnectError as e:
            raise SetuConnectionError(f"Could not reach Setu Gateway at {self.base_url}: {e}") from e
        _raise_for_status(resp)
        return resp.json()

    async def _stream(self, method: str, path: str, **kwargs: Any):
        try:
            async with self._http.stream(method, path, **kwargs) as resp:
                _raise_for_status(resp)
                async for line in resp.aiter_lines():
                    chunk = _parse_sse_line(line)
                    if chunk is not None:
                        yield chunk
        except httpx.ConnectError as e:
            raise SetuConnectionError(f"Could not reach Setu Gateway at {self.base_url}: {e}") from e

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncSetuClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()
