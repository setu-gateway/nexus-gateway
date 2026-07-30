import pytest

from apps.gateway.plugins.loader import PluginLoader
from packages.plugin_sdk import PluginContext
from plugins.hello_world.plugin import HelloWorldPlugin


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
