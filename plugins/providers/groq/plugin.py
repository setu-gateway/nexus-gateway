import json
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
from packages.shared.config.settings import load_settings
from packages.shared.logging.logger import get_logger
from packages.shared.network import retry_provider_call

logger = get_logger("groq_provider")


class GroqProviderPlugin(ProviderPlugin):
    """Groq LPU Provider Adapter. Groq's API is wire-compatible with OpenAI's chat
    completions endpoint, so this mirrors OpenAIProviderPlugin closely rather than
    needing its own request/response translation."""

    name: str = "Groq LPU Provider Adapter"
    provider_name: str = "groq"

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.groq.com/openai/v1"):
        settings = load_settings()
        self.api_key = api_key or (settings.groq_api_key.get_secret_value() if settings.groq_api_key else None)
        self.base_url = base_url.rstrip("/")

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat(self, request: ChatRequest) -> Any:
        if request.stream:
            return self.stream_chat(request)

        if not self.api_key:
            logger.warning("No GROQ_API_KEY configured. Returning fallback mock response.")
            return {
                "id": "chatcmpl-groq-stub",
                "object": "chat.completion",
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": f"Groq LPU response for model '{request.model}'"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 10, "total_tokens": 18},
            }

        url = f"{self.base_url}/chat/completions"
        payload = request.model_dump(exclude_none=True)

        async def _call_api():
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=self._get_headers())
                resp.raise_for_status()
                return resp.json()

        return await retry_provider_call(_call_api, provider_name=self.provider_name)

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        if not self.api_key:
            logger.warning("No GROQ_API_KEY configured. Yielding mock SSE stream chunks.")
            for i, chunk in enumerate(["Groq ", "LPU ", "streaming ", "response"]):
                event = {
                    "id": "chatcmpl-groq-stream-stub",
                    "object": "chat.completion.chunk",
                    "model": request.model,
                    "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": "stop" if i == 3 else None}],
                }
                yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"
            return

        url = f"{self.base_url}/chat/completions"
        payload = request.model_dump(exclude_none=True)
        payload["stream"] = True

        async with (
            httpx.AsyncClient(timeout=60.0) as client,
            client.stream("POST", url, json=payload, headers=self._get_headers()) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    yield f"{line}\n\n"

    async def embeddings(self, request: EmbeddingRequest) -> dict[str, Any]:
        return {"error": "Embeddings not supported on Groq LPU"}

    async def image(self, request: ImageRequest) -> dict[str, Any]:
        return {"error": "Image generation not supported on Groq LPU"}

    async def audio(self, request: AudioRequest) -> dict[str, Any]:
        return {"text": "Groq Whisper audio transcription stub"}

    async def health(self) -> ProviderHealthResponse:
        if not self.api_key:
            return ProviderHealthResponse(status="ok", latency_ms=5.0)
        try:
            url = f"{self.base_url}/models"
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url, headers=self._get_headers())
                if resp.status_code < 500:
                    return ProviderHealthResponse(status="ok", latency_ms=15.0)
                return ProviderHealthResponse(status="degraded", latency_ms=None)
        except Exception:
            return ProviderHealthResponse(status="degraded", latency_ms=None)

    async def models(self) -> ProviderModelResponse:
        return ProviderModelResponse(models=["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "whisper-large-v3"])
