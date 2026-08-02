import asyncio
import time
from collections.abc import Coroutine

# Captured before any test can patch asyncio.sleep (e.g. to fast-forward a retry
# backoff elsewhere - see packages/shared/network/retry.py) - a patch on the asyncio
# module's `sleep` attribute would otherwise silently break drain_background_tasks'
# own polling delay too, since both modules resolve `asyncio.sleep` through the same
# shared module object. Same pattern as tests/test_cli_benchmark.py's
# `_RealAsyncClient = httpx.AsyncClient`.
_real_sleep = asyncio.sleep

# Populated only under test (see tests/conftest.py, which sets _tracking_enabled and
# awaits drain_background_tasks in its autouse fixture). A plain list append/iterate
# is enough here: CPython's GIL makes it safe for the cross-thread use this enables
# (TestClient requests run on its portal's own event loop, on its own thread, separate
# from pytest-asyncio's fixture loop) without needing an explicit lock.
_tracked_tasks: list = []
_tracking_enabled = False


def fire_and_forget(coro: Coroutine) -> "asyncio.Task":
    """Schedule `coro` to run without waiting for it - the shared entrypoint for
    analytics/webhook/audit writes that must never add latency to the request that
    triggered them. A thin wrapper around asyncio.create_task rather than calling it
    directly at each site, so tests have one place to intercept every background task
    instead of racing pytest's fixture teardown against work still in flight on a
    separate event loop.
    """
    task = asyncio.create_task(coro)
    if _tracking_enabled:
        _tracked_tasks.append(task)
    return task


async def drain_background_tasks(timeout: float = 2.0, poll_interval: float = 0.01) -> None:
    """Wait for every tracked fire_and_forget task to finish, then forget them.

    Tasks scheduled via a request made through TestClient live on its portal's own
    event loop/thread, not whichever loop calls this function - awaiting them
    directly here would be a cross-loop operation asyncio doesn't support. Polling
    `.done()` sidesteps that: it's a plain attribute read, safe enough across threads
    for this purpose, so this works regardless of which loop actually owns the task.
    """
    deadline = time.monotonic() + timeout
    while any(not t.done() for t in _tracked_tasks):
        if time.monotonic() > deadline:
            break
        await _real_sleep(poll_interval)
    _tracked_tasks.clear()
