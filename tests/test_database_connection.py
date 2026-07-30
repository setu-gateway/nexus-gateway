import pytest
from apps.gateway.db.session import Base, check_database_connection, engine, get_db_session


@pytest.mark.asyncio
async def test_database_session_exports():
    assert Base is not None
    assert engine is not None


@pytest.mark.asyncio
async def test_get_db_session_generator():
    gen = get_db_session()
    assert gen is not None
