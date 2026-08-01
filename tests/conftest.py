from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
import pytest
import pytest_asyncio

from apps.gateway.db import models  # noqa: F401 - registers all tables on Base.metadata
from apps.gateway.db import session as db_session_module
from apps.gateway.db.base import Base
from apps.gateway.db.session import get_db_session
from apps.gateway.main import app
from apps.gateway.providers.instance import health_monitor, routing_engine

test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

# Patched at the module attribute level (not just via dependency_overrides below) so
# that code which opens its own session directly - e.g. apps/gateway/analytics/recorder.py,
# which deliberately does NOT ride the request-scoped session (see its docstring) - also
# lands on the test database instead of trying to reach a real Postgres.
db_session_module.async_session_factory = TestSessionLocal


async def _get_test_db_session():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db_session] = _get_test_db_session


@pytest_asyncio.fixture(autouse=True)
async def _reset_test_database():
    """Give every test a clean schema against the shared in-memory SQLite engine.

    A file-less SQLite in-memory database only persists for the life of a single
    connection, so the engine uses StaticPool to keep one shared connection alive -
    that's what lets the app's request-scoped sessions and this fixture's own
    session see the same data.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    """Direct DB session for tests that need to set up rows the API can't create."""
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
def _reset_provider_health_state():
    """provider_registry/health_monitor/routing_engine are process-wide singletons
    (apps/gateway/providers/instance.py) shared by every request - and every test.
    Without a reset, one test simulating a provider failure permanently degrades that
    provider's recorded success rate for every test that runs after it in the same
    process, which the routing engine (correctly) treats as real signal."""
    health_monitor._metrics.clear()
    routing_engine._round_robin_counters.clear()
    yield
    health_monitor._metrics.clear()
    routing_engine._round_robin_counters.clear()
