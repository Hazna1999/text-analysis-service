import pytest
import time
from unittest.mock import AsyncMock, patch
from app.services.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_allows_request():
    """Rate limiter allows request when tokens available."""
    limiter = RateLimiter()

    # Mock Redis script to return 1 (allowed)
    mock_script = AsyncMock(return_value=1)
    limiter._script = mock_script

    result = await limiter.allow("tenant-A")
    assert result is True


@pytest.mark.asyncio
async def test_rate_limiter_denies_when_empty():
    """Rate limiter denies request when bucket is empty."""
    limiter = RateLimiter()

    # Mock Redis script to return 0 (denied)
    mock_script = AsyncMock(return_value=0)
    limiter._script = mock_script

    result = await limiter.allow("tenant-A")
    assert result is False


@pytest.mark.asyncio
async def test_rate_limiter_uses_correct_tenant_key():
    """Rate limiter uses tenant specific Redis key."""
    limiter = RateLimiter()

    called_keys = []

    async def capture_keys(keys, args):
        called_keys.extend(keys)
        return 1

    limiter._script = capture_keys

    await limiter.allow("tenant-XYZ")

    assert "rate_limit:tenant-XYZ" in called_keys


@pytest.mark.asyncio
async def test_rate_limiter_different_tenants_independent():
    """Different tenants have independent buckets."""
    limiter = RateLimiter()

    call_count = {"count": 0}

    async def mock_script(keys, args):
        call_count["count"] += 1
        # First tenant allowed, second denied
        if "tenant-A" in keys[0]:
            return 1
        return 0

    limiter._script = mock_script

    result_a = await limiter.allow("tenant-A")
    result_b = await limiter.allow("tenant-B")

    assert result_a is True
    assert result_b is False


@pytest.mark.asyncio
async def test_rate_limiter_passes_correct_args():
    """Rate limiter passes capacity and refill rate to Redis."""
    limiter = RateLimiter()

    captured_args = []

    async def capture_args(keys, args):
        captured_args.extend(args)
        return 1

    limiter._script = capture_args

    await limiter.allow("tenant-A")

    # args = [capacity, refill_rate, timestamp, requested]
    assert len(captured_args) == 4
    assert captured_args[0] == 100   # capacity
    assert captured_args[1] == 10    # refill_rate
    assert captured_args[3] == 1     # requested tokens