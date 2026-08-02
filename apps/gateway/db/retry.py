import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError

from packages.shared.logging.logger import get_logger

logger = get_logger("db_retry")

T = TypeVar("T")


async def with_lock_retry(fn: Callable[[], Awaitable[T]], *, attempts: int = 3, initial_delay: float = 0.05) -> T:
    """Retry `fn` a few times on a transient "database is locked" error before
    giving up.

    SQLite (used in tests; production runs Postgres, which doesn't have this
    limitation) only allows one writer at a time. This gateway's fire-and-forget
    standalone-session writes - analytics, audit, webhooks, cache/time-machine, each
    opening its own session so it isn't tied to the request's own transaction - can
    land close together when several requests overlap, and one can transiently lose
    that race. A short retry clears it without adding latency to the request that
    triggered the write: these all already run off that request's critical path.
    """
    delay = initial_delay
    for attempt in range(attempts):
        try:
            return await fn()
        except OperationalError as e:
            if "locked" not in str(e).lower() or attempt == attempts - 1:
                raise
            logger.debug(f"Retrying after transient database lock (attempt {attempt + 1}/{attempts}): {e}")
            await asyncio.sleep(delay)
            delay *= 2
