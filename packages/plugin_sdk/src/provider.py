from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from packages.plugin_sdk.src.plugin import BasePlugin


class ChatRequest(BaseModel):
    """Schema for Chat Completion requests."""

    model: str = Field(description="Target model identifier")
    messages: list[dict[str, Any]] = Field(description="Conversation message history")
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float | None = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool | None = Field(default=False)
    stop: str | list[str] | None = Field(default=None)


class EmbeddingRequest(BaseModel):
    """Schema for Vector Embedding requests."""

    model: str = Field(description="Target embedding model identifier")
    input: str | list[str] = Field(description="Input text string or list of text strings")


class ImageRequest(BaseModel):
    """Schema for Image Generation requests."""

    prompt: str = Field(description="Text description of the desired image")
    model: str | None = Field(default="dall-e-3")
    n: int | None = Field(default=1, ge=1, le=10)
    size: str | None = Field(default="1024x1024")


class AudioRequest(BaseModel):
    """Schema for Audio Transcription/Speech requests."""

    model: str = Field(default="whisper-1", description="Target audio model")
    file: bytes = Field(description="Audio file binary payload")
    prompt: str | None = Field(default=None)


class ProviderHealthResponse(BaseModel):
    """Schema for Provider Health status."""

    status: str = Field(description="Provider status ('ok', 'degraded', 'offline')")
    latency_ms: float | None = Field(default=None, description="Roundtrip ping latency in milliseconds")


class ProviderModelResponse(BaseModel):
    """Schema for Provider supported models list."""

    models: list[str] = Field(default_factory=list, description="List of supported model identifiers")


class ProviderPlugin(BasePlugin, ABC):
    """Stable Provider Plugin Contract for all LLM Provider Adapters."""

    name: str = "base_provider"
    provider_name: str = "generic"

    @abstractmethod
    async def chat(self, request: ChatRequest) -> dict[str, Any]:
        """Send a chat completion request to the provider."""
        pass

    @abstractmethod
    async def embeddings(self, request: EmbeddingRequest) -> dict[str, Any]:
        """Send a vector embedding request to the provider."""
        pass

    @abstractmethod
    async def image(self, request: ImageRequest) -> dict[str, Any]:
        """Send an image generation request to the provider."""
        pass

    @abstractmethod
    async def audio(self, request: AudioRequest) -> dict[str, Any]:
        """Send an audio transcription/speech request to the provider."""
        pass

    @abstractmethod
    async def health(self) -> ProviderHealthResponse:
        """Query upstream provider health and connectivity latency."""
        pass

    @abstractmethod
    async def models(self) -> ProviderModelResponse:
        """List available models supported by this provider."""
        pass
