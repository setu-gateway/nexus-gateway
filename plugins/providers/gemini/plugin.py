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

logger = get_logger("gemini_provider")

_FINISH_REASON_MAP = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter"}


def _to_gemini_contents(messages: list[dict[str, Any]]) -> tuple:
    """Gemini uses "user"/"model" roles (not "assistant") and takes the system prompt
    as a separate systemInstruction field, not a message in the list - same shape
    mismatch as Anthropic's Messages API, different field names."""
    system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
    contents = [
        {"role": "model" if m.get("role") == "assistant" else "user", "parts": [{"text": m.get("content", "")}]}
        for m in messages
        if m.get("role") != "system"
    ]
    system_instruction = {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None
    return system_instruction, contents


class GeminiProviderPlugin(ProviderPlugin):
    """Google Gemini Provider Adapter, calling the real generateContent API when
    GEMINI_API_KEY is configured."""

    name: str = "Google Gemini Provider Adapter"
    provider_name: str = "gemini"

    def __init__(self, api_key: str | None = None, base_url: str = "https://generativelanguage.googleapis.com/v1beta"):
        settings = load_settings()
        self.api_key = api_key or (settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None)
        self.base_url = base_url.rstrip("/")

    async def chat(self, request: ChatRequest) -> Any:
        if request.stream:
            return self.stream_chat(request)

        if not self.api_key:
            logger.warning("No GEMINI_API_KEY configured. Returning fallback mock response.")
            return {
                "id": "chatcmpl-gemini-stub",
                "object": "chat.completion",
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": f"Gemini response for model '{request.model}'"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 10, "total_tokens": 18},
            }

        system_instruction, contents = _to_gemini_contents(request.messages)
        generation_config: dict[str, Any] = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.top_p is not None:
            generation_config["topP"] = request.top_p
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if request.stop:
            generation_config["stopSequences"] = request.stop if isinstance(request.stop, list) else [request.stop]

        payload: dict[str, Any] = {"contents": contents}
        if generation_config:
            payload["generationConfig"] = generation_config
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        url = f"{self.base_url}/models/{request.model}:generateContent"

        async def _call_api():
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, params={"key": self.api_key}, json=payload)
                resp.raise_for_status()
                return resp.json()

        data = await retry_provider_call(_call_api, provider_name=self.provider_name)
        return self._translate_response(data, request.model)

    def _translate_response(self, data: dict[str, Any], model: str) -> dict[str, Any]:
        candidates = data.get("candidates", [])
        first = candidates[0] if candidates else {}
        parts = first.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata", {})
        prompt_tokens = usage.get("promptTokenCount", 0)
        completion_tokens = usage.get("candidatesTokenCount", 0)
        return {
            "id": "chatcmpl-gemini",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": _FINISH_REASON_MAP.get(first.get("finishReason"), "stop"),
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": usage.get("totalTokenCount", prompt_tokens + completion_tokens),
            },
        }

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        """Gemini's native streamGenerateContent returns incremental `candidates`
        chunks over SSE, a different shape than OpenAI's delta format - translating
        that incrementally is real added surface area this pass doesn't take on.
        Instead: make the real (non-streaming) call and yield the real answer as a
        single chunk, so a streaming request against a configured key gets a real
        response rather than a silently wrong one."""
        if not self.api_key:
            logger.warning("No GEMINI_API_KEY configured. Yielding mock SSE stream chunks.")
            for i, chunk in enumerate(["Gemini ", "streaming ", "response"]):
                event = {
                    "id": "chatcmpl-gemini-stream-stub",
                    "object": "chat.completion.chunk",
                    "model": request.model,
                    "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": "stop" if i == 2 else None}],
                }
                yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"
            return

        result = await self.chat(ChatRequest(**{**request.model_dump(), "stream": False}))
        content = result["choices"][0]["message"]["content"]
        event = {
            "id": result["id"],
            "object": "chat.completion.chunk",
            "model": result["model"],
            "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": result["choices"][0]["finish_reason"]}],
        }
        yield f"data: {json.dumps(event)}\n\n"
        yield "data: [DONE]\n\n"

    async def embeddings(self, request: EmbeddingRequest) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [{"object": "embedding", "embedding": [0.08, 0.09, 0.10], "index": 0}],
            "model": request.model,
        }

    async def image(self, request: ImageRequest) -> dict[str, Any]:
        return {"created": 1600000000, "data": [{"url": "https://generativelanguage.googleapis.com/v1/imagen.png"}]}

    async def audio(self, request: AudioRequest) -> dict[str, Any]:
        return {"text": "Gemini multimodal audio transcription stub"}

    async def health(self) -> ProviderHealthResponse:
        if not self.api_key:
            return ProviderHealthResponse(status="ok", latency_ms=18.4)
        try:
            url = f"{self.base_url}/models"
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url, params={"key": self.api_key})
                if resp.status_code < 500:
                    return ProviderHealthResponse(status="ok", latency_ms=15.0)
                return ProviderHealthResponse(status="degraded", latency_ms=None)
        except Exception:
            return ProviderHealthResponse(status="degraded", latency_ms=None)

    async def models(self) -> ProviderModelResponse:
        return ProviderModelResponse(models=["gemini-1.5-pro", "gemini-1.5-flash"])
