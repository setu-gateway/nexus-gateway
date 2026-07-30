from unittest.mock import AsyncMock, patch
import pytest

from apps.gateway.plugins.loader import PluginLoader
from packages.plugin_sdk import BasePlugin, PluginContext
from plugins.hello_world.plugin import HelloWorldPlugin


class ErrorPlugin(BasePlugin):
    name = "error_plugin"

    async def on_load(self, context=None):
        raise RuntimeError("Load error")

    async def on_request(self, context):
        raise RuntimeError("Request error")

    async def on_response(self, context):
        raise RuntimeError("Response error")

    async def on_unload(self):
        raise RuntimeError("Unload error")


@pytest.mark.asyncio
async def test_hello_world_plugin_direct():
    plugin = HelloWorldPlugin()
    assert plugin.name == "hello_world"
    assert plugin.version == "0.1.0"

    context = PluginContext(request_id="req-101", path="/v1/chat/completions")

    await plugin.on_load(context)
    await plugin.on_request(context)

    assert context.headers.get("X-Hello-Plugin") == "Hello World!"
    assert context.state.get("hello_world_executed") is True

    await plugin.on_response(context)
    assert context.headers.get("X-Hello-Response") == "Processed"

    await plugin.on_unload()


@pytest.mark.asyncio
async def test_plugin_loader_discovery_and_lifecycle():
    loader = PluginLoader()
    discovered = loader.discover_and_load_plugins("plugins")

    assert len(discovered) >= 1
    assert "hello_world" in loader.plugins

    context = PluginContext(request_id="req-202", path="/v1/models")

    await loader.initialize_plugins(context)
    await loader.execute_on_request(context)

    assert context.headers.get("X-Hello-Plugin") == "Hello World!"
    assert context.state.get("hello_world_executed") is True

    await loader.execute_on_response(context)
    assert context.headers.get("X-Hello-Response") == "Processed"

    await loader.unload_plugins()
    assert len(loader.plugins) == 0


@pytest.mark.asyncio
async def test_plugin_loader_error_resilience():
    loader = PluginLoader()
    error_plugin = ErrorPlugin()
    loader.register_plugin(error_plugin)

    context = PluginContext(request_id="req-err")

    # None of these should crash the gateway
    await loader.initialize_plugins(context)
    await loader.execute_on_request(context)
    await loader.execute_on_response(context)
    await loader.unload_plugins()


def test_plugin_loader_nonexistent_directory():
    loader = PluginLoader()
    plugins = loader.discover_and_load_plugins("nonexistent_directory_123")
    assert isinstance(plugins, list)
