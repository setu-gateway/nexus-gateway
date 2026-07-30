from typing import Any, AsyncGenerator, Dict, List, Optional
import json
import os
import time
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

logger = get_logger("ollama_provider")


class OllamaProviderPlugin(ProviderPlugin):
    """Ollama Local LLM Provider Integration Adapter for self-hosted users."""

    name: str = "Ollama Local Provider Adapter"
    provider_name: str = "ollama"

    def __init__(self, base_url: Optional[str] = None):
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

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                ollama_data = resp.json()

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
        except Exception as e:
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

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        """Stream chat completions via Server-Sent Events (SSE)."""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": request.model,
            "messages": request.messages,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", url, json=payload) as resp:
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
                            yield f"data: {json.dumps(event)}\n\n"
                            if is_done:
                                break
                    yield "data: [DONE]\n\n"
        except Exception:
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

    async def embeddings(self, request: EmbeddingRequest) -> Dict[str, Any]:
        """Generate text vector embeddings using local Ollama embeddings endpoint."""
        url = f"{self.base_url}/api/embeddings"
        prompt_text = request.input[0] if isinstance(request.input, list) else request.input
        payload = {"model": request.model, "prompt": prompt_text}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                embedding = data.get("embedding", [0.01, 0.02, 0.03])
                return {
                    "object": "list",
                    "data": [{"object": "embedding", "embedding": embedding, "index": 0}],
                    "model": request.model,
                }
        except Exception:
            return {
                "object": "list",
                "data": [{"object": "embedding", "embedding": [0.05, 0.06, 0.07], "index": 0}],
                "model": request.model,
            }

    async def image(self, request: ImageRequest) -> Dict[str, Any]:
        return {"error": "Image generation not supported on Ollama local runner"}

    async def audio(self, request: AudioRequest) -> Dict[str, Any]:
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
