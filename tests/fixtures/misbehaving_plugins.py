"""Plugins that misbehave on purpose, for exercising apps/gateway/plugins/sandbox.py's
isolation guarantees. Never imported by the gateway itself - test-only."""

from packages.plugin_sdk import BasePlugin, PluginContext


class WellBehavedPlugin(BasePlugin):
    name = "well_behaved"

    async def on_request(self, context: PluginContext) -> None:
        context.headers["X-Sandbox-Test"] = "ok"


class CrashingPlugin(BasePlugin):
    name = "crashing"

    async def on_request(self, context: PluginContext) -> None:
        raise RuntimeError("intentional crash for sandbox testing")


class InfiniteLoopPlugin(BasePlugin):
    name = "infinite_loop"

    async def on_request(self, context: PluginContext) -> None:
        while True:
            pass


class MemoryBombPlugin(BasePlugin):
    name = "memory_bomb"

    async def on_request(self, context: PluginContext) -> None:
        hog = []
        while True:
            hog.append(bytearray(10 * 1024 * 1024))  # 10MB at a time
