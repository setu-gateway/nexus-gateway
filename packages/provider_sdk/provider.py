from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict

from packages.plugin_sdk import BasePlugin
from packages.provider_sdk.capabilities import ProviderCapabilities
from packages.provider_sdk.health import ProviderHealthResponse
from packages.provider_sdk.models import (
    AudioRequest,
    ChatRequest,
    EmbeddingRequest,
    ImageRequest,
    ProviderModelResponse,
)


class BaseProviderPlugin(BasePlugin, ABC):
    """Stable Base Interface contract for all LLM Provider Plugins."""

    name: str = "base_provider"
    provider_name: str = "generic"

    @abstractmethod
    async def chat(self, request: ChatRequest) -> Any:
        """Send a non-streaming chat completion request."""
        pass

    @abstractmethod
    async def stream(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        """Stream token chunks via Server-Sent Events (SSE)."""
        pass

    @abstractmethod
    async def embeddings(self, request: EmbeddingRequest) -> Dict[str, Any]:
        """Send a vector embedding request."""
        pass

    @abstractmethod
    async def models(self) -> ProviderModelResponse:
        """List supported models for this provider."""
        pass

    @abstractmethod
    async def health(self) -> ProviderHealthResponse:
        """Query upstream provider health and latency."""
        pass

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Return capability flags for this provider."""
        pass

    async def image(self, request: ImageRequest) -> Dict[str, Any]:
        """Optional image generation endpoint."""
        return {"error": f"Image generation not supported by provider '{self.provider_name}'"}

    async def audio(self, request: AudioRequest) -> Dict[str, Any]:
        """Optional audio transcription endpoint."""
        return {"error": f"Audio transcription not supported by provider '{self.provider_name}'"}
