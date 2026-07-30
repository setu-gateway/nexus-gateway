from pydantic import BaseModel, Field


class ProviderCapabilities(BaseModel):
    """Capability flags for a provider."""

    chat: bool = Field(default=True, description="Supports chat completions")
    embeddings: bool = Field(default=False, description="Supports vector embeddings")
    image: bool = Field(default=False, description="Supports image generation")
    audio: bool = Field(default=False, description="Supports audio transcription / speech")
    streaming: bool = Field(default=True, description="Supports SSE token streaming")
    tools: bool = Field(default=True, description="Supports function calling / tools")
    vision: bool = Field(default=False, description="Supports multimodal vision input")
