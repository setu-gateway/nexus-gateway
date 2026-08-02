from unittest.mock import AsyncMock

import pytest

from apps.gateway.redis.client import (
    RedisStreamClient,
    check_redis_connection,
    close_redis_connection,
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
    is_alive = await check_redis_connection()
    assert isinstance(is_alive, bool)


@pytest.mark.asyncio
async def test_close_redis_connection():
    await close_redis_connection()


@pytest.mark.asyncio
async def test_redis_stream_client_operations():
    mock_redis = AsyncMock()
    mock_redis.xadd.return_value = "1620000000000-0"
    mock_redis.xread.return_value = [["test-stream", [("1620000000000-0", {"key": "val"})]]]
    mock_redis.xgroup_create.return_value = True
    mock_redis.xreadgroup.return_value = []
    mock_redis.xack.return_value = 1

    stream_client = RedisStreamClient(client=mock_redis)

    msg_id = await stream_client.publish_event("test-stream", {"event": "login"})
    assert msg_id == "1620000000000-0"

    read_res = await stream_client.read_events("test-stream")
    assert len(read_res) == 1

    group_created = await stream_client.create_consumer_group("test-stream", "group1")
    assert group_created is True

    group_read = await stream_client.read_group_events("test-stream", "group1", "consumer1")
    assert group_read == []

    ack_res = await stream_client.ack_event("test-stream", "group1", "1620000000000-0")
    assert ack_res == 1
