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


class GroqProviderPlugin(ProviderPlugin):
    """Groq Ultra-Fast Inference Provider Integration Adapter."""

    name: str = "Groq LPU Provider Adapter"
    provider_name: str = "groq"

    async def chat(self, request: ChatRequest) -> Dict[str, Any]:
        return {
            "id": "chatcmpl-groq-stub",
            "object": "chat.completion",
            "model": request.model,
            "choices": [{"message": {"role": "assistant", "content": f"Groq LPU response for model '{request.model}'"}}],
        }

    async def embeddings(self, request: EmbeddingRequest) -> Dict[str, Any]:
        return {"error": "Embeddings not supported on Groq LPU"}

    async def image(self, request: ImageRequest) -> Dict[str, Any]:
        return {"error": "Image generation not supported on Groq LPU"}

    async def audio(self, request: AudioRequest) -> Dict[str, Any]:
        return {"text": "Groq Whisper audio transcription stub"}

    async def health(self) -> ProviderHealthResponse:
        return ProviderHealthResponse(status="ok", latency_ms=3.1)

    async def models(self) -> ProviderModelResponse:
        return ProviderModelResponse(models=["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "whisper-large-v3"])
