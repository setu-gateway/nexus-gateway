import time
from dataclasses import dataclass

from apps.gateway.redis.client import get_redis_client
from packages.shared.logging.logger import get_logger

logger = get_logger("rate_limiter")

_KEY_PREFIX = "setu:ratelimit"

# Token bucket needs check-then-decrement to be atomic across concurrent requests
# hitting the same key, which a plain GET/SET round trip can't guarantee - a Lua
# script runs as a single atomic operation on the Redis server instead. (This is
# script source, not a credential - the nosec below is for bandit's B105 heuristic,
# which flags string literals assigned to a variable name containing "token".)
_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local bucket = redis.call("HMGET", key, "tokens", "last_refill")
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
  tokens = capacity
  last_refill = now
end

local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end

redis.call("HMSET", key, "tokens", tostring(tokens), "last_refill", tostring(now))
redis.call("EXPIRE", key, ttl)

return {allowed, tostring(tokens)}
"""  # nosec B105


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: float
    retry_after_seconds: float


class RateLimiter:
    """Redis-backed rate limiting (Epic 5.4) across three algorithms, keyed by an
    arbitrary (scope_type, scope_value) pair - callers decide what that pair means
    (org, project, API key, provider, endpoint, ...). Fails OPEN on any Redis error:
    a rate limiter's job is protective, not core to serving traffic, so an outage in
    Redis should degrade to "unlimited" rather than take the whole gateway down -
    matching the resilience posture apps/gateway/cache/manager.py already established
    for its Redis tier.
    """

    def __init__(self) -> None:
        self._token_bucket_sha: str = None  # type: ignore[assignment]

    def _key(self, algorithm: str, scope_type: str, scope_value: str) -> str:
        return f"{_KEY_PREFIX}:{algorithm}:{scope_type}:{scope_value}"

    async def check(
        self,
        scope_type: str,
        scope_value: str,
        limit: int,
        window_seconds: int,
        algorithm: str = "sliding_window",
    ) -> RateLimitResult:
        try:
            if algorithm == "fixed_window":
                return await self._fixed_window(scope_type, scope_value, limit, window_seconds)
            if algorithm == "token_bucket":
                return await self._token_bucket(scope_type, scope_value, limit, window_seconds)
            return await self._sliding_window(scope_type, scope_value, limit, window_seconds)
        except Exception as e:
            logger.warning(f"Rate limiter unavailable (failing open) for {scope_type}:{scope_value}: {e}")
            return RateLimitResult(allowed=True, limit=limit, remaining=limit, retry_after_seconds=0.0)

    async def _fixed_window(self, scope_type: str, scope_value: str, limit: int, window_seconds: int) -> RateLimitResult:
        client = get_redis_client()
        now = time.time()
        window_index = int(now // window_seconds)
        key = f"{self._key('fixed', scope_type, scope_value)}:{window_index}"

        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)

        window_end = (window_index + 1) * window_seconds
        return RateLimitResult(
            allowed=count <= limit,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after_seconds=max(0.0, window_end - now) if count > limit else 0.0,
        )

    async def _sliding_window(self, scope_type: str, scope_value: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Sliding window counter approximation: blends the previous fixed window's
        count (weighted by how much of it still falls inside the sliding window) with
        the current window's count. Two INCR/EXPIRE round trips instead of a precise
        sorted-set log, trading a small approximation error for O(1) memory per key."""
        client = get_redis_client()
        now = time.time()
        window_index = int(now // window_seconds)
        elapsed_fraction = (now % window_seconds) / window_seconds

        current_key = f"{self._key('sliding', scope_type, scope_value)}:{window_index}"
        previous_key = f"{self._key('sliding', scope_type, scope_value)}:{window_index - 1}"

        current_count = await client.incr(current_key)
        if current_count == 1:
            await client.expire(current_key, window_seconds * 2)
        previous_count = int(await client.get(previous_key) or 0)

        weighted_count = previous_count * (1 - elapsed_fraction) + current_count
        return RateLimitResult(
            allowed=weighted_count <= limit,
            limit=limit,
            remaining=max(0.0, limit - weighted_count),
            retry_after_seconds=max(0.0, window_seconds * (1 - elapsed_fraction)) if weighted_count > limit else 0.0,
        )

    async def _token_bucket(self, scope_type: str, scope_value: str, limit: int, window_seconds: int) -> RateLimitResult:
        client = get_redis_client()
        if self._token_bucket_sha is None:
            self._token_bucket_sha = await client.script_load(_TOKEN_BUCKET_SCRIPT)

        key = self._key("bucket", scope_type, scope_value)
        refill_rate = limit / window_seconds
        now = time.time()
        ttl = int(window_seconds) + 60
        try:
            allowed, remaining = await client.evalsha(self._token_bucket_sha, 1, key, limit, refill_rate, now, ttl)
        except Exception:
            # SHA not cached on this Redis instance (e.g. a restart/failover) - reload once.
            self._token_bucket_sha = await client.script_load(_TOKEN_BUCKET_SCRIPT)
            allowed, remaining = await client.evalsha(self._token_bucket_sha, 1, key, limit, refill_rate, now, ttl)

        remaining_f = float(remaining)
        return RateLimitResult(
            allowed=bool(int(allowed)),
            limit=limit,
            remaining=remaining_f,
            retry_after_seconds=0.0 if int(allowed) else max(0.0, (1 - remaining_f) / refill_rate),
        )
