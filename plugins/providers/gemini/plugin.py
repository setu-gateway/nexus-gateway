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


class GeminiProviderPlugin(ProviderPlugin):
    """Google Gemini Provider Integration Adapter."""

    name: str = "Google Gemini Provider Adapter"
    provider_name: str = "gemini"

    async def chat(self, request: ChatRequest) -> Dict[str, Any]:
        return {
            "id": "chatcmpl-gemini-stub",
            "object": "chat.completion",
            "model": request.model,
            "choices": [{"message": {"role": "assistant", "content": f"Gemini response for model '{request.model}'"}}],
        }

    async def embeddings(self, request: EmbeddingRequest) -> Dict[str, Any]:
        return {
            "object": "list",
            "data": [{"object": "embedding", "embedding": [0.08, 0.09, 0.10], "index": 0}],
            "model": request.model,
        }

    async def image(self, request: ImageRequest) -> Dict[str, Any]:
        return {"created": 1600000000, "data": [{"url": "https://generativelanguage.googleapis.com/v1/imagen.png"}]}

    async def audio(self, request: AudioRequest) -> Dict[str, Any]:
        return {"text": "Gemini multimodal audio transcription stub"}

    async def health(self) -> ProviderHealthResponse:
        return ProviderHealthResponse(status="ok", latency_ms=18.4)

    async def models(self) -> ProviderModelResponse:
        return ProviderModelResponse(models=["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash-exp"])
