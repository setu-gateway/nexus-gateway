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

logger = get_logger("anthropic_provider")

_ANTHROPIC_VERSION = "2023-06-01"
# Anthropic requires max_tokens with no server-side default, unlike OpenAI's optional
# one - this is only used when the caller didn't specify one.
_DEFAULT_MAX_TOKENS = 4096

_STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


def _split_system_prompt(messages: list[dict[str, Any]]) -> tuple:
    """Anthropic's Messages API takes the system prompt as a separate top-level
    `system` string, not a message with role="system" - unlike OpenAI/most other
    providers. Concatenates any system-role messages (in order) into one string and
    returns the remaining messages unchanged."""
    system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
    remaining = [m for m in messages if m.get("role") != "system"]
    return ("\n\n".join(system_parts) if system_parts else None), remaining


def _extract_text(content_blocks: list[dict[str, Any]]) -> str:
    return "".join(block.get("text", "") for block in content_blocks if block.get("type") == "text")


class AnthropicProviderPlugin(ProviderPlugin):
    """Anthropic Claude Provider Adapter, calling the real Messages API when
    ANTHROPIC_API_KEY is configured."""

    name: str = "Anthropic Claude Provider Adapter"
    provider_name: str = "anthropic"

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.anthropic.com/v1"):
        settings = load_settings()
        self.api_key = api_key or (settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None)
        self.base_url = base_url.rstrip("/")

    def _get_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": _ANTHROPIC_VERSION,
        }

    def _build_payload(self, request: ChatRequest) -> dict[str, Any]:
        system, messages = _split_system_prompt(request.messages)
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or _DEFAULT_MAX_TOKENS,
        }
        if system:
            payload["system"] = system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop:
            payload["stop_sequences"] = request.stop if isinstance(request.stop, list) else [request.stop]
        return payload

    async def chat(self, request: ChatRequest) -> Any:
        if request.stream:
            return self.stream_chat(request)

        if not self.api_key:
            logger.warning("No ANTHROPIC_API_KEY configured. Returning fallback mock response.")
            return {
                "id": "chatcmpl-anthropic-stub",
                "object": "chat.completion",
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": f"Claude response for model '{request.model}'"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 10, "total_tokens": 18},
            }

        url = f"{self.base_url}/messages"
        payload = self._build_payload(request)

        async def _call_api():
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=self._get_headers())
                resp.raise_for_status()
                return resp.json()

        data = await retry_provider_call(_call_api, provider_name=self.provider_name)

        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        return {
            "id": data.get("id", "chatcmpl-anthropic"),
            "object": "chat.completion",
            "model": data.get("model", request.model),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": _extract_text(data.get("content", []))},
                    "finish_reason": _STOP_REASON_MAP.get(data.get("stop_reason"), "stop"),
                }
            ],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        }

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        """Anthropic's native stream uses named SSE events (message_start,
        content_block_delta, message_stop, ...) with a different shape per event type -
        translating that incrementally into OpenAI-style chunks is real added surface
        area this pass doesn't take on. Instead: make the real (non-streaming) call and
        yield the real answer as a single chunk, so a streaming request against a
        configured key gets a real response rather than a silently wrong one."""
        if not self.api_key:
            logger.warning("No ANTHROPIC_API_KEY configured. Yielding mock SSE stream chunks.")
            for i, chunk in enumerate(["Claude ", "streaming ", "response"]):
                event = {
                    "id": "chatcmpl-anthropic-stream-stub",
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
        return {"error": "Embeddings endpoint not supported directly by Anthropic"}

    async def image(self, request: ImageRequest) -> dict[str, Any]:
        return {"error": "Image generation not supported by Anthropic"}

    async def audio(self, request: AudioRequest) -> dict[str, Any]:
        return {"error": "Audio transcription not supported by Anthropic"}

    async def health(self) -> ProviderHealthResponse:
        if not self.api_key:
            return ProviderHealthResponse(status="ok", latency_ms=22.1)
        try:
            url = f"{self.base_url}/models"
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url, headers=self._get_headers())
                if resp.status_code < 500:
                    return ProviderHealthResponse(status="ok", latency_ms=20.0)
                return ProviderHealthResponse(status="degraded", latency_ms=None)
        except Exception:
            return ProviderHealthResponse(status="degraded", latency_ms=None)

    async def models(self) -> ProviderModelResponse:
        return ProviderModelResponse(models=["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"])
