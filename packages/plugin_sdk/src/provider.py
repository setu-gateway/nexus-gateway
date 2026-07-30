from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from packages.plugin_sdk.src.plugin import BasePlugin


class ChatRequest(BaseModel):
    """Schema for Chat Completion requests."""

    model: str = Field(description="Target model identifier")
    messages: List[Dict[str, Any]] = Field(description="Conversation message history")
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    stream: Optional[bool] = Field(default=False)
    stop: Optional[Union[str, List[str]]] = Field(default=None)


class EmbeddingRequest(BaseModel):
    """Schema for Vector Embedding requests."""

    model: str = Field(description="Target embedding model identifier")
    input: Union[str, List[str]] = Field(description="Input text string or list of text strings")


class ImageRequest(BaseModel):
    """Schema for Image Generation requests."""

    prompt: str = Field(description="Text description of the desired image")
    model: Optional[str] = Field(default="dall-e-3")
    n: Optional[int] = Field(default=1, ge=1, le=10)
    size: Optional[str] = Field(default="1024x1024")


class AudioRequest(BaseModel):
    """Schema for Audio Transcription/Speech requests."""

    model: str = Field(default="whisper-1", description="Target audio model")
    file: bytes = Field(description="Audio file binary payload")
    prompt: Optional[str] = Field(default=None)


class ProviderHealthResponse(BaseModel):
    """Schema for Provider Health status."""

    status: str = Field(description="Provider status ('ok', 'degraded', 'offline')")
    latency_ms: Optional[float] = Field(default=None, description="Roundtrip ping latency in milliseconds")


class ProviderModelResponse(BaseModel):
    """Schema for Provider supported models list."""

    models: List[str] = Field(default_factory=list, description="List of supported model identifiers")


class ProviderPlugin(BasePlugin, ABC):
    """Stable Provider Plugin Contract for all LLM Provider Adapters."""

    name: str = "base_provider"
    provider_name: str = "generic"

    @abstractmethod
    async def chat(self, request: ChatRequest) -> Dict[str, Any]:
        """Send a chat completion request to the provider."""
        pass

    @abstractmethod
    async def embeddings(self, request: EmbeddingRequest) -> Dict[str, Any]:
        """Send a vector embedding request to the provider."""
        pass

    @abstractmethod
    async def image(self, request: ImageRequest) -> Dict[str, Any]:
        """Send an image generation request to the provider."""
        pass

    @abstractmethod
    async def audio(self, request: AudioRequest) -> Dict[str, Any]:
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
