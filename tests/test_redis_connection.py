import pytest
from apps.gateway.redis.client import (
    RedisStreamClient,
    check_redis_connection,
    get_redis_client,
    redis_pool,
)


@pytest.mark.asyncio
async def test_redis_connection_pool():
    assert redis_pool is not None
    client = get_redis_client()
    assert client is not None


@pytest.mark.asyncio
async def test_redis_healthcheck_fallback():
    # Health check returns boolean without raising unhandled exceptions
    is_alive = await check_redis_connection()
    assert isinstance(is_alive, bool)


@pytest.mark.asyncio
async def test_redis_stream_client_init():
    stream_client = RedisStreamClient()
    assert stream_client is not None
    assert stream_client.client is not None
