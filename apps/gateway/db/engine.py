import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://setu:setu_pass@localhost:5432/setu_db",
)

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("LOG_LEVEL", "info").lower() == "debug",
    pool_pre_ping=True,
    # Every in-flight request holds its session's connection for the request's full
    # duration (apps/gateway/db/session.py's get_db_session commits only after the
    # endpoint returns), so pool capacity is a hard ceiling on concurrent requests, not
    # just a throughput knob. Sprint 6's benchmark (100/1k/10k requests at concurrency
    # 20-100) hit the previous 10+20=30 ceiling directly - requests past it queued for
    # up to pool_timeout and then failed with QueuePool TimeoutError. Defaults raised
    # accordingly and made tunable per-deployment via env vars instead of another
    # hardcoded ceiling.
    pool_size=int(os.getenv("DB_POOL_SIZE", "20")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "30")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "30")),
)


async def check_database_connection() -> bool:
    """Check connection to the PostgreSQL database."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception:
        return False
