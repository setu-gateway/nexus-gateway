"""Subprocess-isolated plugin execution (Epic 7.3's marketplace security follow-up).

The default `PluginLoader` (apps/gateway/plugins/loader.py) imports a plugin's code
directly into the gateway process and calls its hooks in-process - fine for the
bundled, reviewed plugins under `plugins/`, but not an acceptable trust boundary for
a plugin sourced from the marketplace, which `marketplace/DESIGN.md` names
explicitly as an open problem. `SandboxedPluginRunner` runs a plugin's hook in a
separate OS process instead, with CPU-time and memory limits and a wall-clock
timeout, so a hung, memory-hungry, or crashing plugin can't take the gateway process
down with it.

What this does and does not protect against, honestly:
- DOES stop a plugin from corrupting the gateway's own process memory, reading
  other in-process state (other plugins' data, request/response objects it wasn't
  explicitly given), hanging the request indefinitely, or leaking memory/CPU
  without bound - each of these is enforced at the OS process boundary, not by
  trusting the plugin's own code to behave.
- Does NOT stop the plugin process from making its own outbound network calls -
  full network egress control needs OS-level enforcement (network namespaces, an
  egress proxy allowlist) that a pure-Python subprocess boundary can't provide.
  Do not represent this as "the plugin can't exfiltrate data" - it can, over the
  network, same as before. It can no longer do so by corrupting the host process.
- Uses the POSIX `resource` module, so none of this applies on Windows at all -
  same as before, nothing about plugin execution was cross-platform-safe without
  this either.
- The memory ceiling (RLIMIT_AS) is Linux-only in practice: verified that macOS's
  kernel unconditionally rejects setting it (raises "current limit exceeds maximum
  limit" for any value), so on macOS the sandbox silently skips just that one limit
  and still enforces CPU-time + wall-clock timeout + process isolation. Linux -
  what infrastructure/docker/Dockerfile.gateway actually ships - supports it fully.
"""

import asyncio
import contextlib
import importlib
import multiprocessing
import queue
import resource
import sys
from dataclasses import dataclass

from packages.plugin_sdk import BasePlugin, PluginContext

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_CPU_SECONDS = 2
DEFAULT_MEMORY_MB = 128


class PluginSandboxError(Exception):
    """Raised when a sandboxed plugin hook fails, times out, or is killed for
    exceeding its resource limits."""


@dataclass
class SandboxLimits:
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cpu_seconds: int = DEFAULT_CPU_SECONDS
    memory_mb: int = DEFAULT_MEMORY_MB


def _instantiate_plugin(entry_point: str) -> BasePlugin:
    """entry_point is 'dotted.module.path.ClassName', matching the marketplace
    manifest schema's entryPoint field (marketplace/schema/plugin-manifest.schema.json)."""
    module_path, _, class_name = entry_point.rpartition(".")
    if not module_path:
        raise PluginSandboxError(f"Invalid entry point '{entry_point}': expected 'module.path.ClassName'")
    module = importlib.import_module(module_path)
    plugin_class = getattr(module, class_name, None)
    if plugin_class is None or not (isinstance(plugin_class, type) and issubclass(plugin_class, BasePlugin)):
        raise PluginSandboxError(f"'{entry_point}' does not name a BasePlugin subclass")
    return plugin_class()


def _apply_resource_limits(cpu_seconds: int, memory_mb: int) -> None:
    """Runs inside the child process, before any plugin code executes. A hard CPU
    limit sends SIGXCPU (fatal by default) once exceeded.

    The memory limit (RLIMIT_AS) is best-effort, not guaranteed: verified on this
    project's actual dev platform (macOS/Darwin) that the kernel unconditionally
    rejects setrlimit(RLIMIT_AS, ...) with "current limit exceeds maximum limit"
    regardless of the value requested - Darwin does not support an address-space
    rlimit the way Linux does. Linux (what infrastructure/docker/Dockerfile.gateway
    actually ships) does support it. Rather than crash the sandbox on platforms
    where this one limit isn't available, skip it and fall back to CPU-time +
    wall-clock timeout + process isolation - still real containment, just not a
    hard memory ceiling. Do not remove this fallback to "simplify" - doing so
    breaks the sandbox entirely on macOS, not just the memory limit.
    """
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    memory_bytes = memory_mb * 1024 * 1024
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


def _sandbox_worker(
    entry_point: str,
    hook_name: str,
    context_data: dict,
    cpu_seconds: int,
    memory_mb: int,
    result_queue: "multiprocessing.Queue[dict]",
    parent_sys_path: list[str],
) -> None:
    """Top-level (picklable) target for multiprocessing's 'spawn' start method,
    which macOS and Windows require and Linux defaults to safely as well - a
    closure or bound method can't be used here.

    A freshly spawned interpreter does not inherit the parent's sys.path
    modifications (only PYTHONPATH and the standard install locations) - a plugin
    installed somewhere non-standard (a marketplace plugin in its own directory, a
    test fixture under a path pytest added dynamically) would otherwise be
    importable in the main gateway process but not in the sandbox. Propagating the
    parent's sys.path makes the sandbox see exactly what the caller sees.
    """
    for path in parent_sys_path:
        if path not in sys.path:
            sys.path.append(path)
    try:
        _apply_resource_limits(cpu_seconds, memory_mb)
        plugin = _instantiate_plugin(entry_point)
        hook = getattr(plugin, hook_name)
        context = PluginContext(**context_data)

        async def _run() -> PluginContext:
            result = await hook(context)
            return result if isinstance(result, PluginContext) else context

        final_context = asyncio.run(_run())
        result_queue.put({"ok": True, "context": final_context.model_dump()})
    except Exception as e:  # noqa: BLE001 - deliberately broad: any plugin exception must not crash the sandbox
        result_queue.put({"ok": False, "error": f"{type(e).__name__}: {e}"})


class SandboxedPluginRunner:
    """Runs a single plugin hook in an isolated subprocess and returns the
    (possibly mutated) PluginContext, or raises PluginSandboxError."""

    def __init__(self, limits: SandboxLimits | None = None):
        self.limits = limits or SandboxLimits()

    async def run_hook(self, entry_point: str, hook_name: str, context: PluginContext) -> PluginContext:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run_hook_sync, entry_point, hook_name, context)

    def _run_hook_sync(self, entry_point: str, hook_name: str, context: PluginContext) -> PluginContext:
        ctx = multiprocessing.get_context("spawn")
        result_queue: multiprocessing.Queue = ctx.Queue()
        process = ctx.Process(
            target=_sandbox_worker,
            args=(entry_point, hook_name, context.model_dump(), self.limits.cpu_seconds, self.limits.memory_mb, result_queue, sys.path),
        )
        process.start()
        process.join(timeout=self.limits.timeout_seconds)

        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
            raise PluginSandboxError(f"Plugin '{entry_point}'.{hook_name} exceeded {self.limits.timeout_seconds}s wall-clock timeout")

        try:
            result = result_queue.get_nowait()
        except queue.Empty as e:
            # Process exited without putting a result - typically SIGKILL/SIGXCPU/SIGSEGV
            # from the resource limits or the OS, not a Python-catchable exception.
            raise PluginSandboxError(
                f"Plugin '{entry_point}'.{hook_name} terminated abnormally (exit code {process.exitcode}), "
                f"likely from exceeding its {self.limits.memory_mb}MB memory or {self.limits.cpu_seconds}s CPU limit"
            ) from e

        if not result["ok"]:
            raise PluginSandboxError(f"Plugin '{entry_point}'.{hook_name} raised: {result['error']}")

        return PluginContext(**result["context"])
