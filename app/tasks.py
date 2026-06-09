import asyncio
import logging
from arq.connections import RedisSettings
from sqlalchemy import select, update
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Batch, BatchItem
from app.services.third_party import analyze_text

logger = logging.getLogger(__name__)


async def process_batch(ctx, batch_id: str):
    """
    Main worker task.
    1. Marks batch as processing
    2. Fetches all pending items
    3. Processes them concurrently (capped by semaphore)
    4. Updates batch status when done
    """
    logger.info(f"Starting batch {batch_id}")

    # Semaphore limits concurrent requests
    # e.g. max 10 items processed at the same time
    semaphore = asyncio.Semaphore(settings.max_concurrent_requests)

    # Get tenant_id and mark batch as processing
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Batch).where(Batch.id == batch_id)
        )
        batch = result.scalar_one_or_none()
        if not batch:
            logger.error(f"Batch {batch_id} not found")
            return

        tenant_id = batch.tenant_id

        await db.execute(
            update(Batch)
            .where(Batch.id == batch_id)
            .values(status="processing")
        )
        await db.commit()

    # Fetch all pending items
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BatchItem).where(
                BatchItem.batch_id == batch_id,
                BatchItem.status == "pending",
            )
        )
        items = result.scalars().all()

    logger.info(f"Batch {batch_id} has {len(items)} pending items")

    # Process all items concurrently but capped
    tasks = [
        _process_item(
            item.id,
            batch_id,
            tenant_id,
            item.text,
            semaphore
        )
        for item in items
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Finalize batch status
    await _finalize_batch(batch_id)
    logger.info(f"Batch {batch_id} finished")


async def _process_item(
    item_id: str,
    batch_id: str,
    tenant_id: str,
    text: str,
    semaphore: asyncio.Semaphore,
):
    async with semaphore:

        # Idempotency check — skip if already processed
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BatchItem).where(BatchItem.id == item_id)
            )
            item = result.scalar_one_or_none()
            if not item or item.status in ("success", "failed"):
                return

            # Mark as processing to prevent double processing
            await db.execute(
                update(BatchItem)
                .where(
                    BatchItem.id == item_id,
                    BatchItem.status == "pending"
                )
                .values(status="processing")
            )
            await db.commit()

        try:
            # Call mock third party API
            result = await analyze_text(tenant_id, item_id, text)

            # Save success
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(BatchItem)
                    .where(BatchItem.id == item_id)
                    .values(
                        status="success",
                        result=result,
                        attempt_count=BatchItem.attempt_count + 1
                    )
                )
                await db.execute(
                    update(Batch)
                    .where(Batch.id == batch_id)
                    .values(done_items=Batch.done_items + 1)
                )
                await db.commit()

            logger.info(f"Item {item_id} succeeded")

        except Exception as e:
            # Save permanent failure
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(BatchItem)
                    .where(BatchItem.id == item_id)
                    .values(
                        status="failed",
                        last_error=str(e),
                        attempt_count=BatchItem.attempt_count + 1
                    )
                )
                await db.execute(
                    update(Batch)
                    .where(Batch.id == batch_id)
                    .values(failed_items=Batch.failed_items + 1)
                )
                await db.commit()

            logger.error(f"Item {item_id} permanently failed: {e}")


async def _finalize_batch(batch_id: str):
    """Set final batch status based on results."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Batch).where(Batch.id == batch_id)
        )
        batch = result.scalar_one()

        if batch.failed_items == 0:
            final_status = "completed"
        elif batch.done_items == 0:
            final_status = "failed"
        else:
            final_status = "partially_failed"

        await db.execute(
            update(Batch)
            .where(Batch.id == batch_id)
            .values(status=final_status)
        )
        await db.commit()
        logger.info(f"Batch {batch_id} finalized as {final_status}")


# ── Arq Worker Settings ────────────────────────────────────────
class WorkerSettings:
    functions = [process_batch]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10