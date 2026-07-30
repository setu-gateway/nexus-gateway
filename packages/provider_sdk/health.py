from typing import Optional
from pydantic import BaseModel, Field


class ProviderHealthResponse(BaseModel):
    """Schema for Provider Health status."""

    status: str = Field(description="Provider status ('ok', 'degraded', 'offline')")
    latency_ms: Optional[float] = Field(default=None, description="Roundtrip ping latency in milliseconds")
