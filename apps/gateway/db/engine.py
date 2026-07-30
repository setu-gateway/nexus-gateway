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
    pool_size=10,
    max_overflow=20,
)


async def check_database_connection() -> bool:
    """Check connection to the PostgreSQL database."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception:
        return False
