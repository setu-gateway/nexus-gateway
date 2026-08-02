from abc import ABC
from typing import Any

from pydantic import BaseModel, Field


class PluginContext(BaseModel):
    """Context passed to plugins during execution phases."""

    request_id: str = ""
    trace_id: str = ""
    path: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)


class BasePlugin(ABC):
    """Abstract Base Class for Setu Gateway Plugins."""

    name: str = "base_plugin"
    version: str = "0.1.0"
    description: str = "Base plugin interface"

    async def on_load(self, context: PluginContext | None = None) -> None:
        """Invoked when the plugin is loaded into the gateway."""
        pass

    async def on_request(self, context: PluginContext) -> None:
        """Invoked on incoming request processing."""
        pass

    async def on_response(self, context: PluginContext) -> None:
        """Invoked on outgoing response processing."""
        pass

    async def on_unload(self) -> None:
        """Invoked when the gateway shuts down or unloads the plugin."""
        pass
