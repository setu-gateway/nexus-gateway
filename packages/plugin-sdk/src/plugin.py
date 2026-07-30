from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class PluginContext(BaseModel):
    """Context passed to plugins during execution phases."""

    request_id: str = ""
    trace_id: str = ""
    path: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    state: Dict[str, Any] = Field(default_factory=dict)


class BasePlugin(ABC):
    """Abstract Base Class for Nexus Gateway Plugins."""

    name: str = "base_plugin"
    version: str = "0.1.0"
    description: str = "Base plugin interface"

    async def on_load(self, context: Optional[PluginContext] = None) -> None:
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
