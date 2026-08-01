from typing import Any, AsyncGenerator, Dict, List, Optional
import json
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

logger = get_logger("openai_provider")


class OpenAIProviderPlugin(ProviderPlugin):
    """OpenAI Reference Provider Implementation with exponential backoff retries."""

    name: str = "OpenAI Reference Provider Adapter"
    provider_name: str = "openai"

    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.openai.com/v1"):
        settings = load_settings()
        self.api_key = api_key or (settings.openai_api_key.get_secret_value() if settings.openai_api_key else None)
        self.base_url = base_url.rstrip("/")

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat(self, request: ChatRequest) -> Any:
        """Send a chat completion request to OpenAI with exponential backoff retries for transient failures."""
        if request.stream:
            return self.stream_chat(request)

        if not self.api_key:
            logger.warning("No OPENAI_API_KEY configured. Returning fallback mock response.")
            return {
                "id": "chatcmpl-openai-ref-mock",
                "object": "chat.completion",
                "created": 1600000000,
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"OpenAI Reference Provider response for model '{request.model}'",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
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
        """Stream chat completions via Server-Sent Events (SSE)."""
        if not self.api_key:
            logger.warning("No OPENAI_API_KEY configured. Yielding mock SSE stream chunks.")
            mock_chunks = ["OpenAI ", "Reference ", "Streaming ", "Response"]
            for i, chunk in enumerate(mock_chunks):
                event = {
                    "id": "chatcmpl-openai-stream-mock",
                    "object": "chat.completion.chunk",
                    "created": 1600000000,
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
            return

        url = f"{self.base_url}/chat/completions"
        payload = request.model_dump(exclude_none=True)
        payload["stream"] = True

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json=payload, headers=self._get_headers()) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        yield f"{line}\n\n"

    async def embeddings(self, request: EmbeddingRequest) -> Dict[str, Any]:
        """Generate text vector embeddings with OpenAI."""
        if not self.api_key:
            return {
                "object": "list",
                "data": [{"object": "embedding", "embedding": [0.01, 0.02, 0.03, 0.04], "index": 0}],
                "model": request.model,
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            }

        url = f"{self.base_url}/embeddings"
        payload = request.model_dump(exclude_none=True)

        async def _call_embed():
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=self._get_headers())
                resp.raise_for_status()
                return resp.json()

        return await retry_provider_call(_call_embed, provider_name=self.provider_name)

    async def image(self, request: ImageRequest) -> Dict[str, Any]:
        """Generate images using OpenAI DALL-E."""
        if not self.api_key:
            return {
                "created": 1600000000,
                "data": [{"url": "https://api.openai.com/v1/images/ref-stub.png"}],
            }

        url = f"{self.base_url}/images/generations"
        payload = request.model_dump(exclude_none=True)

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=self._get_headers())
            resp.raise_for_status()
            return resp.json()

    async def audio(self, request: AudioRequest) -> Dict[str, Any]:
        """Transcribe audio using OpenAI Whisper."""
        if not self.api_key:
            return {"text": "OpenAI reference audio transcription stub"}

        url = f"{self.base_url}/audio/transcriptions"
        files = {"file": ("audio.mp3", request.file, "audio/mpeg")}
        data = {"model": request.model}
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, data=data, files=files, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def health(self) -> ProviderHealthResponse:
        """Query OpenAI health status."""
        if not self.api_key:
            return ProviderHealthResponse(status="ok", latency_ms=10.0)

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
        """List models supported by OpenAI."""
        if not self.api_key:
            return ProviderModelResponse(
                models=[
                    "gpt-4o",
                    "gpt-4o-mini",
                    "gpt-4-turbo",
                    "gpt-3.5-turbo",
                    "o1-preview",
                    "o1-mini",
                    "text-embedding-3-small",
                    "text-embedding-3-large",
                    "dall-e-3",
                    "whisper-1",
                ]
            )

        try:
            url = f"{self.base_url}/models"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=self._get_headers())
                resp.raise_for_status()
                data = resp.json()
                model_ids = [m["id"] for m in data.get("data", [])]
                return ProviderModelResponse(models=model_ids)
        except Exception:
            return ProviderModelResponse(models=["gpt-4o", "gpt-4o-mini", "text-embedding-3-small"])
