from typing import Any, Dict
from packages.plugin_sdk import (
    AudioRequest,
    ChatRequest,
    EmbeddingRequest,
    ImageRequest,
    ProviderHealthResponse,
    ProviderModelResponse,
    ProviderPlugin,
)


class AnthropicProviderPlugin(ProviderPlugin):
    """Anthropic Claude Provider Integration Adapter."""

    name: str = "Anthropic Claude Provider Adapter"
    provider_name: str = "anthropic"

    async def chat(self, request: ChatRequest) -> Dict[str, Any]:
        return {
            "id": "chatcmpl-anthropic-stub",
            "object": "chat.completion",
            "model": request.model,
            "choices": [{"message": {"role": "assistant", "content": f"Claude response for model '{request.model}'"}}],
        }

    async def embeddings(self, request: EmbeddingRequest) -> Dict[str, Any]:
        return {"error": "Embeddings endpoint not supported directly by Anthropic"}

    async def image(self, request: ImageRequest) -> Dict[str, Any]:
        return {"error": "Image generation not supported by Anthropic"}

    async def audio(self, request: AudioRequest) -> Dict[str, Any]:
        return {"error": "Audio transcription not supported by Anthropic"}

    async def health(self) -> ProviderHealthResponse:
        return ProviderHealthResponse(status="ok", latency_ms=22.1)

    async def models(self) -> ProviderModelResponse:
        return ProviderModelResponse(models=["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"])
