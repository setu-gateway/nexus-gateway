import asyncio
import gc
import uuid

import fakeredis.aioredis
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

import apps.gateway.redis.client as redis_client_module
import apps.gateway.utils.background as background_module
from apps.gateway.db import models  # noqa: F401 - registers all tables on Base.metadata
from apps.gateway.db import session as db_session_module
from apps.gateway.db.base import Base
from apps.gateway.db.session import get_db_session
from apps.gateway.main import app
from apps.gateway.providers.instance import cache_manager, health_monitor, rate_limiter, routing_engine
from apps.gateway.utils.background import drain_background_tasks

# Every fire_and_forget() call (analytics/webhook/audit writes - see
# apps/gateway/utils/background.py) gets tracked so _reset_test_database's teardown
# can drain them deterministically instead of racing pytest's fixture teardown
# against work still in flight on TestClient's own portal thread/event loop.
background_module._tracking_enabled = True

test_engine = create_async_engine(
    # A plain ":memory:" URL makes SQLAlchemy auto-select StaticPool, forcing every
    # session in the process onto ONE physical connection - fine when sessions are
    # used strictly one at a time, but a streaming request's session stays open for
    # the life of its SSE generator, which can overlap with a fire-and-forget task's
    # own standalone session (apps/gateway/analytics/recorder.py and friends, plus
    # apps/gateway/cache/manager.py's set_standalone). Two Session objects sharing one
    # physical connection don't know about each other, and a commit on one has been
    # observed to corrupt the other's, up to and including making already-created
    # tables briefly report "no such table" - even when the held-open session never
    # itself wrote anything. A named shared-cache in-memory database plus a real
    # pool (poolclass must be explicit - SQLAlchemy overrides it back to StaticPool
    # otherwise for anything that looks like a SQLite memory URL) gives each session
    # its own real connection while all of them still see the same data.
    "sqlite+aiosqlite:///file:setu_test_db?mode=memory&cache=shared&uri=true",
    connect_args={"check_same_thread": False, "timeout": 10},
    poolclass=AsyncAdaptedQueuePool,
)
TestSessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

# Patched at the module attribute level (not just via dependency_overrides below) so
# that code which opens its own session directly - e.g. apps/gateway/analytics/recorder.py,
# which deliberately does NOT ride the request-scoped session (see its docstring) - also
# lands on the test database instead of trying to reach a real Postgres.
db_session_module.async_session_factory = TestSessionLocal


async def _run_with_lock_retry(fn, *, attempts: int = 5, initial_delay: float = 0.05) -> None:
    """Requests made through TestClient run on its own portal thread/event loop, so
    fire-and-forget work they schedule (audit logging, webhooks, cache/time-machine
    standalone writes - see apps/gateway/analytics/recorder.py and friends) can still
    be mid-transaction against test_engine when a test function returns. Retrying a
    few times with a short backoff clears a transient lock once that other
    connection's transaction finishes, at zero cost to the (overwhelmingly common)
    uncontended case.
    """
    delay = initial_delay
    for attempt in range(attempts):
        try:
            await fn()
            return
        except OperationalError as e:
            if "locked" not in str(e).lower() or attempt == attempts - 1:
                raise
            await asyncio.sleep(delay)
            delay *= 2


async def retry_on_lock(fn, *, attempts: int = 5, initial_delay: float = 0.05):
    """Same idea as _run_with_lock_retry above, for a plain synchronous callable (a
    TestClient request) instead of an awaitable one - for a test's own mutating call
    that can transiently race a fire-and-forget write (audit logging, etc.) from a
    request made just before it, the same way this whole module's other locking
    comments describe. Draining tracked background tasks first (drain_background_tasks)
    closes most of that race already; this is the backstop for what's left - e.g. a
    write from a source this process didn't happen to track, or one that started after
    the drain's own poll loop already returned. Returns fn()'s result so callers can
    still use the response (e.g. `resp = await retry_on_lock(lambda: client.delete(...))`)."""
    delay = initial_delay
    for attempt in range(attempts):
        try:
            return fn()
        except OperationalError as e:
            if "locked" not in str(e).lower() or attempt == attempts - 1:
                raise
            await asyncio.sleep(delay)
            delay *= 2


async def _get_test_db_session():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db_session] = _get_test_db_session


async def _create_schema_once() -> None:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


asyncio.run(_create_schema_once())


@pytest_asyncio.fixture(autouse=True)
async def _reset_test_database():
    """Give every test a clean slate against the shared in-memory SQLite engine.

    The schema is created once at import time (above) and never dropped - clearing
    it between tests is done by deleting every row rather than DROP/CREATE TABLE,
    because DROP TABLE needs an exclusive lock on sqlite_master that a still-running
    fire-and-forget write (see _run_with_lock_retry's docstring) can hold well past
    the point a test function returns; busy_timeout does not reliably cover that
    schema-level lock the way it does an ordinary row/table DML lock, but a DELETE
    here is exactly that ordinary case and just waits it out. Foreign key enforcement
    is off by default in SQLite (confirmed: `PRAGMA foreign_keys` reads 0) and
    nothing in this codebase turns it on, so table deletion order doesn't matter.

    test_engine's URL uses SQLite's shared-cache URI mode, which is what lets the
    app's request-scoped sessions, fire-and-forget standalone sessions, and this
    fixture's own session all see the same data despite each getting its own real
    connection (see the longer comment on test_engine's definition above).

    drain_background_tasks() runs first in teardown so that fire-and-forget writes
    triggered by the test (audit logging, webhooks, cache/time-machine standalone
    writes) finish - and stop touching test_engine - before the DELETE pass, rather
    than relying on _run_with_lock_retry alone to paper over the remainder. A finished
    task's own connection is already checked back into the pool by the time it's
    done, but SQLAlchemy also finalizes abandoned (never-checked-in) connections via
    garbage collection - an explicit gc.collect() forces any of those to run HERE,
    at a controlled point, instead of firing unpredictably during the DELETE pass
    below and colliding with it.
    """

    async def _clear_all_tables():
        async with test_engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(table.delete())

    await _run_with_lock_retry(_clear_all_tables)
    yield
    await drain_background_tasks()
    gc.collect()
    await _run_with_lock_retry(_clear_all_tables)


@pytest_asyncio.fixture
async def db_session():
    """Direct DB session for tests that need to set up rows the API can't create."""
    async with TestSessionLocal() as session:
        yield session


def register_and_login(client: TestClient, email: str | None = None, password: str = "testpassword123") -> tuple[str, dict[str, str]]:
    """Registers a fresh user (creating their own new organization + default
    project - see POST /auth/register) and logs in. Returns (organization_id,
    auth_headers) for exercising dashboard-management endpoints that now require a
    real, authenticated user rather than the unauthenticated access they used to
    silently allow."""
    email = email or f"test-{uuid.uuid4().hex[:8]}@example.com"
    register_resp = client.post("/auth/register", json={"email": email, "password": password})
    assert register_resp.status_code == 201, register_resp.text
    org_id = register_resp.json()["organization_id"]

    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["access_token"]

    return org_id, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def authed_org() -> tuple[str, dict[str, str]]:
    """The common case: one freshly-registered user and their own organization,
    ready to use as (org_id, headers) wherever a test needs an authenticated actor
    but doesn't care who specifically."""
    return register_and_login(TestClient(app))


@pytest.fixture(autouse=True)
def _reset_provider_health_state():
    """provider_registry/health_monitor/routing_engine are process-wide singletons
    (apps/gateway/providers/instance.py) shared by every request - and every test.
    Without a reset, one test simulating a provider failure permanently degrades that
    provider's recorded success rate for every test that runs after it in the same
    process, which the routing engine (correctly) treats as real signal. Same idea for
    the rate limiter (Epic 5.4): it's pointed at a fresh FakeRedis instance every test
    rather than a real Redis, and rebuilt (not just cleared) each time since
    tests/test_redis_connection.py::test_close_redis_connection legitimately resets
    the module's singleton to None as part of what it's testing."""
    health_monitor._metrics.clear()
    routing_engine._round_robin_counters.clear()
    cache_manager._memory.clear()
    rate_limiter._token_bucket_sha = None
    redis_client_module._redis_client_instance = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield
    health_monitor._metrics.clear()
    routing_engine._round_robin_counters.clear()
    cache_manager._memory.clear()
