from typing import Optional
from packages.plugin_sdk import BasePlugin, PluginContext
from packages.shared.logging.logger import get_logger

logger = get_logger("plugin.hello_world")


class HelloWorldPlugin(BasePlugin):
    """Simple Hello World Plugin proving the Gateway Plugin Architecture."""

    name: str = "hello_world"
    version: str = "0.1.0"
    description: str = "Demonstration Hello World plugin"

    async def on_load(self, context: Optional[PluginContext] = None) -> None:
        logger.info("Hello World Plugin initialized successfully!")

    async def on_request(self, context: PluginContext) -> None:
        context.headers["X-Hello-Plugin"] = "Hello World!"
        context.state["hello_world_executed"] = True
        logger.info("Hello World Plugin executed on_request", extra={"request_id": context.request_id})

    async def on_response(self, context: PluginContext) -> None:
        context.headers["X-Hello-Response"] = "Processed"
        logger.info("Hello World Plugin executed on_response", extra={"request_id": context.request_id})

    async def on_unload(self) -> None:
        logger.info("Hello World Plugin unloaded cleanly")
