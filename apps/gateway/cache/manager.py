import json
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.db import session as db_session_module
from apps.gateway.db.models import CacheEntry, CachePolicy
from apps.gateway.db.retry import with_lock_retry
from apps.gateway.redis.client import get_redis_client
from packages.shared.logging.logger import get_logger

logger = get_logger("cache_manager")

DEFAULT_TTL_SECONDS = 3600
MEMORY_CACHE_MAX_ENTRIES = 500
REDIS_KEY_PREFIX = "setu:cache:"


@dataclass
class CachedResponse:
    response_body: dict[str, Any]
    is_streaming: bool
    stream_chunks: list[str] | None
    source: str  # "memory" | "redis" | "postgres"


@dataclass
class _MemoryItem:
    response_body: dict[str, Any]
    is_streaming: bool
    stream_chunks: list[str] | None
    expires_at: datetime


class CacheManager:
    """Intelligent cache (Epic 5.1): Memory -> Redis -> Postgres, in that order for
    reads (fastest tier first) and written to all three tiers together so a later read
    can hit whichever tier is fastest. Memory is a simple in-process LRU - fine for a
    modular monolith (RFC-0002); horizontally-scaled deployments still get correct
    (if slower) hits via Redis/Postgres.
    """

    def __init__(self, memory_max_entries: int = MEMORY_CACHE_MAX_ENTRIES):
        self._memory: OrderedDict[str, _MemoryItem] = OrderedDict()
        self._memory_max_entries = memory_max_entries

    def _memory_get(self, cache_key: str) -> _MemoryItem | None:
        item = self._memory.get(cache_key)
        if not item:
            return None
        if item.expires_at <= datetime.now(timezone.utc):
            del self._memory[cache_key]
            return None
        self._memory.move_to_end(cache_key)
        return item

    def _memory_set(self, cache_key: str, item: _MemoryItem) -> None:
        self._memory[cache_key] = item
        self._memory.move_to_end(cache_key)
        while len(self._memory) > self._memory_max_entries:
            self._memory.popitem(last=False)

    def _memory_clear(self, project_id: str | None = None) -> None:
        # Memory tier doesn't track project scoping (it's a small hot-key cache, not
        # the source of truth) - a project-scoped clear conservatively drops everything
        # rather than risk serving a stale entry past invalidation.
        self._memory.clear()

    async def get_policy(self, project_id: str | None, db: AsyncSession) -> CachePolicy:
        if project_id:
            result = await db.execute(select(CachePolicy).where(CachePolicy.project_id == uuid.UUID(project_id)))
            policy = result.scalar_one_or_none()
            if policy:
                return policy
        return CachePolicy(project_id=None, enabled=True, ttl_seconds=DEFAULT_TTL_SECONDS)

    async def get(self, cache_key: str, db: AsyncSession) -> CachedResponse | None:
        memory_item = self._memory_get(cache_key)
        if memory_item:
            return CachedResponse(
                response_body=memory_item.response_body,
                is_streaming=memory_item.is_streaming,
                stream_chunks=memory_item.stream_chunks,
                source="memory",
            )

        try:
            redis_client = get_redis_client()
            raw = await redis_client.get(f"{REDIS_KEY_PREFIX}{cache_key}")
        except Exception as e:
            logger.warning(f"Redis cache tier unavailable, falling through to Postgres: {e}")
            raw = None

        if raw:
            data = json.loads(raw)
            expires_at = datetime.fromisoformat(data["expires_at"])
            if expires_at > datetime.now(timezone.utc):
                self._memory_set(
                    cache_key,
                    _MemoryItem(data["response_body"], data["is_streaming"], data.get("stream_chunks"), expires_at),
                )
                return CachedResponse(data["response_body"], data["is_streaming"], data.get("stream_chunks"), "redis")

        result = await db.execute(
            select(CacheEntry).where(CacheEntry.cache_key == cache_key, CacheEntry.expires_at > datetime.now(timezone.utc))
        )
        entry = result.scalar_one_or_none()
        if entry:
            entry.hit_count += 1
            await db.flush()
            self._memory_set(
                cache_key,
                _MemoryItem(entry.response_body, entry.is_streaming, entry.stream_chunks, entry.expires_at),
            )
            return CachedResponse(entry.response_body, entry.is_streaming, entry.stream_chunks, "postgres")

        return None

    async def set(
        self,
        cache_key: str,
        response_body: dict[str, Any],
        provider: str,
        model: str,
        db: AsyncSession,
        project_id: str | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        is_streaming: bool = False,
        stream_chunks: list[str] | None = None,
    ) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        self._memory_set(cache_key, _MemoryItem(response_body, is_streaming, stream_chunks, expires_at))

        try:
            redis_client = get_redis_client()
            payload = json.dumps(
                {
                    "response_body": response_body,
                    "is_streaming": is_streaming,
                    "stream_chunks": stream_chunks,
                    "expires_at": expires_at.isoformat(),
                }
            )
            await redis_client.set(f"{REDIS_KEY_PREFIX}{cache_key}", payload, ex=max(1, ttl_seconds))
        except Exception as e:
            logger.warning(f"Failed to write cache entry to Redis (memory/Postgres tiers still written): {e}")

        try:
            existing = await db.execute(select(CacheEntry).where(CacheEntry.cache_key == cache_key))
            entry = existing.scalar_one_or_none()
            if entry:
                entry.response_body = response_body
                entry.is_streaming = is_streaming
                entry.stream_chunks = stream_chunks
                entry.expires_at = expires_at
            else:
                db.add(
                    CacheEntry(
                        id=uuid.uuid4(),
                        cache_key=cache_key,
                        project_id=uuid.UUID(project_id) if project_id else None,
                        provider=provider,
                        model=model,
                        response_body=response_body,
                        is_streaming=is_streaming,
                        stream_chunks=stream_chunks,
                        expires_at=expires_at,
                    )
                )
            await db.flush()
        except Exception as e:
            logger.warning(f"Failed to persist cache entry to Postgres (memory/Redis tiers still written): {e}")

    async def set_standalone(self, **kwargs: Any) -> None:
        """Same as `set()`, but opens its own DB session rather than requiring the
        caller to have one on hand. For writing a streaming response to cache: that
        only happens after the SSE generator is fully drained, which is well after the
        original request handler (and its injected, request-scoped session) has
        returned - mirrors apps/gateway/analytics/recorder.py's record_request for the
        same reason.
        """

        async def _write() -> None:
            async with db_session_module.async_session_factory() as session:
                await self.set(db=session, **kwargs)
                await session.commit()

        try:
            await with_lock_retry(_write)
        except Exception as e:
            logger.warning(f"Failed to write standalone cache entry: {e}")

    async def invalidate(self, db: AsyncSession, project_id: str | None = None, cache_key: str | None = None) -> int:
        """Clear cache entries. Passing neither filter clears everything (`setu cache
        clear`); passing project_id scopes to one project's entries."""
        self._memory_clear(project_id)

        try:
            redis_client = get_redis_client()
            if cache_key:
                await redis_client.delete(f"{REDIS_KEY_PREFIX}{cache_key}")
            else:
                async for key in redis_client.scan_iter(match=f"{REDIS_KEY_PREFIX}*"):
                    await redis_client.delete(key)
        except Exception as e:
            logger.warning(f"Failed to clear Redis cache tier: {e}")

        query = delete(CacheEntry)
        if cache_key:
            query = query.where(CacheEntry.cache_key == cache_key)
        elif project_id:
            query = query.where(CacheEntry.project_id == uuid.UUID(project_id))
        result = await db.execute(query)
        await db.flush()
        return result.rowcount or 0
