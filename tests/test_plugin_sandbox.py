import time

import pytest

from apps.gateway.plugins.sandbox import PluginSandboxError, SandboxedPluginRunner, SandboxLimits
from packages.plugin_sdk import PluginContext

WELL_BEHAVED = "tests.fixtures.misbehaving_plugins.WellBehavedPlugin"
CRASHING = "tests.fixtures.misbehaving_plugins.CrashingPlugin"
INFINITE_LOOP = "tests.fixtures.misbehaving_plugins.InfiniteLoopPlugin"
MEMORY_BOMB = "tests.fixtures.misbehaving_plugins.MemoryBombPlugin"


@pytest.mark.asyncio
async def test_well_behaved_plugin_runs_and_mutates_context():
    runner = SandboxedPluginRunner()
    context = PluginContext(request_id="req-1")

    result = await runner.run_hook(WELL_BEHAVED, "on_request", context)

    assert result.headers["X-Sandbox-Test"] == "ok"
    assert result.request_id == "req-1"


@pytest.mark.asyncio
async def test_crashing_plugin_raises_sandbox_error_not_a_raw_exception():
    runner = SandboxedPluginRunner()
    with pytest.raises(PluginSandboxError, match="RuntimeError"):
        await runner.run_hook(CRASHING, "on_request", PluginContext())


@pytest.mark.asyncio
async def test_infinite_loop_plugin_is_killed_by_timeout():
    runner = SandboxedPluginRunner(limits=SandboxLimits(timeout_seconds=1.0, cpu_seconds=10, memory_mb=128))

    start = time.monotonic()
    with pytest.raises(PluginSandboxError, match="timeout"):
        await runner.run_hook(INFINITE_LOOP, "on_request", PluginContext())
    elapsed = time.monotonic() - start

    # Proves the *wall-clock* timeout fired, not just that it eventually errored -
    # an infinite loop with no I/O would otherwise never return control at all.
    assert elapsed < 3.0


@pytest.mark.asyncio
async def test_memory_bomb_plugin_is_killed_by_memory_limit():
    # A tight CPU limit as a backstop: on a fast machine RLIMIT_AS may raise
    # MemoryError (caught, reported via the queue) before RLIMIT_CPU would fire,
    # and on a slow one CPU exhaustion may win instead - either is an acceptable
    # sandbox outcome, both are exercised by the other tests, this one specifically
    # confirms the plugin's runaway allocation never returns a "successful" result.
    runner = SandboxedPluginRunner(limits=SandboxLimits(timeout_seconds=5.0, cpu_seconds=2, memory_mb=64))
    with pytest.raises(PluginSandboxError):
        await runner.run_hook(MEMORY_BOMB, "on_request", PluginContext())


@pytest.mark.asyncio
async def test_invalid_entry_point_raises_clear_error():
    runner = SandboxedPluginRunner()
    with pytest.raises(PluginSandboxError, match="not_a_module"):
        await runner.run_hook("not_a_module.NotAClass", "on_request", PluginContext())


@pytest.mark.asyncio
async def test_entry_point_not_a_plugin_subclass_raises_clear_error():
    runner = SandboxedPluginRunner()
    with pytest.raises(PluginSandboxError, match="BasePlugin"):
        await runner.run_hook("json.JSONEncoder", "on_request", PluginContext())


@pytest.mark.asyncio
async def test_real_bundled_plugin_runs_correctly_in_sandbox():
    """The existing, trusted, bundled hello_world plugin - proving the sandbox is a
    drop-in replacement for direct in-process execution, not just able to run
    test fixtures."""
    runner = SandboxedPluginRunner()
    result = await runner.run_hook("plugins.hello_world.plugin.HelloWorldPlugin", "on_request", PluginContext(request_id="req-2"))
    assert result.headers["X-Hello-Plugin"] == "Hello World!"
    assert result.state["hello_world_executed"] is True
