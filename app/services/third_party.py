import asyncio
import random
import logging
import httpx
from app.config import settings
from app.services.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


async def analyze_text(tenant_id: str, item_id: str, text: str) -> str:
    """
    Call the mock third party API with retry logic.

    - Respects rate limiter before each attempt
    - On 429: waits Retry-After seconds
    - On 5xx: exponential backoff with jitter
    - After max retries: raises Exception (item marked as failed)
    """
    max_retries = settings.max_retries

    async with httpx.AsyncClient(timeout=30.0) as client:
        attempt = 0

        while attempt < max_retries:

            # ── Wait for rate limit token ──────────────────────
            while not await rate_limiter.allow(tenant_id):
                logger.info(f"[{tenant_id}] Rate limited — waiting 1s")
                await asyncio.sleep(1)

            try:
                response = await client.post(
                    f"{settings.third_party_api_url}/v1/analyze",
                    headers={
                        "X-API-Key": settings.third_party_api_key
                    },
                    json={
                        "id": item_id,
                        "text": text
                    },
                )

                # ── Success ────────────────────────────────────
                if response.status_code == 200:
                    data = response.json()
                    return data.get("result", "")

                # ── Rate limited by third party ────────────────
                elif response.status_code == 429:
                    retry_after = int(
                        response.headers.get("Retry-After", 5)
                    )
                    logger.warning(
                        f"[{item_id}] Third party 429 — "
                        f"waiting {retry_after}s"
                    )
                    await asyncio.sleep(retry_after)
                    continue  # don't count as attempt

                # ── Server error ───────────────────────────────
                elif response.status_code >= 500:
                    raise Exception(
                        f"Server error {response.status_code}"
                    )

                # ── Unexpected error ───────────────────────────
                else:
                    raise Exception(
                        f"Unexpected status {response.status_code}"
                    )

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.warning(f"[{item_id}] Network error: {e}")
                if attempt + 1 >= max_retries:
                    raise Exception(
                        f"Network error after {max_retries} attempts: {e}"
                    )

            # ── Exponential backoff with jitter ────────────────
            attempt += 1
            if attempt < max_retries:
                backoff = min(2 ** attempt + random.uniform(0, 1), 60)
                logger.warning(
                    f"[{item_id}] Attempt {attempt} failed — "
                    f"retrying in {backoff:.1f}s"
                )
                await asyncio.sleep(backoff)

    raise Exception(f"Exhausted {max_retries} retries for item {item_id}")