import json
import os
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from packages.plugin_sdk import (
    AudioRequest,
    ChatRequest,
    EmbeddingRequest,
    ImageRequest,
    ProviderHealthResponse,
    ProviderModelResponse,
    ProviderPlugin,
)
from packages.shared.logging.logger import get_logger
from packages.shared.network import retry_provider_call

logger = get_logger("ollama_provider")

# Only "can't reach the daemon at all" gets the friendly local-dev mock fallback below -
# an active connection that errors (bad request, model not found, persistent 5xx after
# retries) propagates instead, so health_monitor/the router see the real failure rather
# than a silent fake success (Epic 4.4: a retry engine is pointless if the wrapped call
# never actually raises).
_CONNECTION_UNAVAILABLE_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


class OllamaProviderPlugin(ProviderPlugin):
    """Ollama Local LLM Provider Integration Adapter for self-hosted users."""

    name: str = "Ollama Local Provider Adapter"
    provider_name: str = "ollama"

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")

    async def chat(self, request: ChatRequest) -> Any:
        """Send chat completion request to local Ollama server."""
        if request.stream:
            return self.stream_chat(request)

        url = f"{self.base_url}/api/chat"
        payload = {
            "model": request.model,
            "messages": request.messages,
            "stream": False,
            "options": {},
        }
        if request.temperature is not None:
            payload["options"]["temperature"] = request.temperature
        if request.top_p is not None:
            payload["options"]["top_p"] = request.top_p

        async def _call_api():
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()

        try:
            ollama_data = await retry_provider_call(_call_api, provider_name=self.provider_name)
        except _CONNECTION_UNAVAILABLE_ERRORS as e:
            logger.warning(f"Ollama server unreachable at {self.base_url}. Yielding mock response ({str(e)}).")
            return {
                "id": "chatcmpl-ollama-fallback",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Ollama local response for model '{request.model}'",
                        },
                        "finish_reason": "stop",
                    }
                ],
            }

        # Translate Ollama response format into OpenAI-compatible format
        return {
            "id": f"chatcmpl-ollama-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": ollama_data.get("message", {}).get("role", "assistant"),
                        "content": ollama_data.get("message", {}).get("content", ""),
                    },
                    "finish_reason": "stop" if ollama_data.get("done") else None,
                }
            ],
            "usage": {
                "prompt_tokens": ollama_data.get("prompt_eval_count", 0),
                "completion_tokens": ollama_data.get("eval_count", 0),
                "total_tokens": ollama_data.get("prompt_eval_count", 0) + ollama_data.get("eval_count", 0),
            },
        }

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        """Stream chat completions via Server-Sent Events (SSE)."""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": request.model,
            "messages": request.messages,
            "stream": True,
        }

        any_real_chunk_sent = False
        try:
            async with httpx.AsyncClient(timeout=60.0) as client, client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        is_done = data.get("done", False)

                        event = {
                            "id": "chatcmpl-ollama-stream",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": request.model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": content},
                                    "finish_reason": "stop" if is_done else None,
                                }
                            ],
                        }
                        any_real_chunk_sent = True
                        yield f"data: {json.dumps(event)}\n\n"
                        if is_done:
                            break
                yield "data: [DONE]\n\n"
        except _CONNECTION_UNAVAILABLE_ERRORS:
            # Only fall back to a fake stream for "never got started" failures - once
            # real content has already gone out, blending in mock chunks after it would
            # silently corrupt the response instead of just ending it.
            if any_real_chunk_sent:
                raise
            # Fallback stream when server is offline
            mock_chunks = ["Ollama ", "Local ", "Streaming ", "Response"]
            for i, chunk in enumerate(mock_chunks):
                event = {
                    "id": "chatcmpl-ollama-stream-mock",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": request.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": chunk},
                            "finish_reason": "stop" if i == len(mock_chunks) - 1 else None,
                        }
                    ],
                }
                yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"

    async def embeddings(self, request: EmbeddingRequest) -> dict[str, Any]:
        """Generate text vector embeddings using local Ollama embeddings endpoint."""
        url = f"{self.base_url}/api/embeddings"
        prompt_text = request.input[0] if isinstance(request.input, list) else request.input
        payload = {"model": request.model, "prompt": prompt_text}

        async def _call_embed():
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()

        try:
            data = await retry_provider_call(_call_embed, provider_name=self.provider_name)
            embedding = data.get("embedding", [0.01, 0.02, 0.03])
            return {
                "object": "list",
                "data": [{"object": "embedding", "embedding": embedding, "index": 0}],
                "model": request.model,
            }
        except _CONNECTION_UNAVAILABLE_ERRORS:
            return {
                "object": "list",
                "data": [{"object": "embedding", "embedding": [0.05, 0.06, 0.07], "index": 0}],
                "model": request.model,
            }

    async def image(self, request: ImageRequest) -> dict[str, Any]:
        return {"error": "Image generation not supported on Ollama local runner"}

    async def audio(self, request: AudioRequest) -> dict[str, Any]:
        return {"error": "Audio transcription not supported on Ollama local runner"}

    async def health(self) -> ProviderHealthResponse:
        """Ping local Ollama server health."""
        url = f"{self.base_url}/api/version"
        try:
            start = time.time()
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                latency = round((time.time() - start) * 1000, 2)
                if resp.status_code == 200:
                    return ProviderHealthResponse(status="ok", latency_ms=latency)
                return ProviderHealthResponse(status="degraded", latency_ms=latency)
        except Exception:
            return ProviderHealthResponse(status="offline", latency_ms=None)

    async def models(self) -> ProviderModelResponse:
        """Discover locally pulled Ollama models from /api/tags."""
        url = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                model_names = [m.get("name") for m in data.get("models", []) if m.get("name")]
                return ProviderModelResponse(models=model_names or ["llama3.2", "mistral", "qwen2.5"])
        except Exception:
            return ProviderModelResponse(models=["llama3.2", "mistral", "qwen2.5", "phi3", "gemma2"])
