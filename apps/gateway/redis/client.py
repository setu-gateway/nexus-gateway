import os
from typing import Any, Dict, List, Optional, Union

import redis.asyncio as aioredis
from redis.asyncio.connection import ConnectionPool
from redis.exceptions import ResponseError

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

redis_pool: ConnectionPool = ConnectionPool.from_url(
    REDIS_URL,
    max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "20")),
    decode_responses=True,
)

_redis_client_instance: Optional[aioredis.Redis] = None


def get_redis_client() -> aioredis.Redis:
    """Get or initialize the shared async Redis client instance using the connection pool."""
    global _redis_client_instance
    if _redis_client_instance is None:
        _redis_client_instance = aioredis.Redis(connection_pool=redis_pool)
    return _redis_client_instance


async def close_redis_connection() -> None:
    """Gracefully close the Redis client and connection pool."""
    global _redis_client_instance
    if _redis_client_instance is not None:
        await _redis_client_instance.aclose()
        _redis_client_instance = None
    await redis_pool.aclose()


async def check_redis_connection() -> bool:
    """Health check function to test Redis connectivity."""
    try:
        client = get_redis_client()
        return bool(await client.ping())
    except Exception:
        return False


class RedisStreamClient:
    """Client for publishing and consuming Redis Streams events."""

    def __init__(self, client: Optional[aioredis.Redis] = None):
        self.client = client or get_redis_client()

    async def publish_event(
        self,
        stream_name: str,
        data: Dict[str, Any],
        max_len: Optional[int] = 10000,
    ) -> str:
        """Publish an event payload to a Redis Stream (XADD)."""
        string_data = {str(k): str(v) for k, v in data.items()}
        return await self.client.xadd(
            name=stream_name,
            fields=string_data,
            maxlen=max_len,
            approximate=True,
        )

    async def read_events(
        self,
        stream_name: str,
        count: int = 10,
        block_ms: int = 1000,
        last_id: str = "$",
    ) -> List[Any]:
        """Read pending stream events (XREAD)."""
        results = await self.client.xread(
            streams={stream_name: last_id},
            count=count,
            block=block_ms,
        )
        return results

    async def create_consumer_group(
        self,
        stream_name: str,
        group_name: str,
        mkstream: bool = True,
        start_id: str = "$",
    ) -> bool:
        """Create a Redis Stream consumer group (XGROUP CREATE)."""
        try:
            await self.client.xgroup_create(
                name=stream_name,
                groupname=group_name,
                id=start_id,
                mkstream=mkstream,
            )
            return True
        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                return True
            raise e

    async def read_group_events(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> List[Any]:
        """Read stream events for a specific consumer group (XREADGROUP)."""
        results = await self.client.xreadgroup(
            groupname=group_name,
            consumername=consumer_name,
            streams={stream_name: ">"},
            count=count,
            block=block_ms,
        )
        return results

    async def ack_event(
        self,
        stream_name: str,
        group_name: str,
        message_id: str,
    ) -> int:
        """Acknowledge a processed stream event (XACK)."""
        return await self.client.xack(stream_name, group_name, message_id)
