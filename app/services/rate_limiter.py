import time
import redis.asyncio as aioredis
from app.config import settings

# ── Lua Script ─────────────────────────────────────────────────
# This runs ATOMICALLY inside Redis
# Meaning: no other process can interrupt it
# This is what makes rate limiting work across multiple workers
TOKEN_BUCKET_LUA = """
local key         = KEYS[1]
local capacity    = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now         = tonumber(ARGV[3])
local requested   = tonumber(ARGV[4])

-- Read current bucket state
local bucket      = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens      = tonumber(bucket[1]) or capacity
local last_refill = tonumber(bucket[2]) or now

-- Calculate new tokens since last check
local elapsed     = math.max(0, now - last_refill)
local new_tokens  = math.min(capacity, tokens + elapsed * refill_rate)

if new_tokens >= requested then
    -- Allow request — consume one token
    redis.call('HMSET', key, 'tokens', new_tokens - requested, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return 1
else
    -- Deny request — not enough tokens
    redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return 0
end
"""

# ── Per tenant config ──────────────────────────────────────────
# capacity    = max tokens in bucket
# refill_rate = tokens added per second
TENANT_CONFIG = {
    "default": {"capacity": 100, "refill_rate": 10},
}


class RateLimiter:
    def __init__(self):
        self.redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True
        )
        self._script = None

    async def _get_script(self):
        if not self._script:
            self._script = self.redis.register_script(TOKEN_BUCKET_LUA)
        return self._script

    async def allow(self, tenant_id: str) -> bool:
        """
        Returns True if tenant is allowed to make a request.
        Returns False if rate limit exceeded.
        """
        config = TENANT_CONFIG.get(
            tenant_id,
            TENANT_CONFIG["default"]
        )
        script = await self._get_script()
        result = await script(
            keys=[f"rate_limit:{tenant_id}"],
            args=[
                config["capacity"],
                config["refill_rate"],
                time.time(),
                1
            ],
        )
        return result == 1


# Single instance used across the whole app
rate_limiter = RateLimiter()