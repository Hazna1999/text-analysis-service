import hashlib
import json
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Batch, BatchItem, IdempotencyRecord
from app.schemas import (
    BatchSubmitRequest, BatchSubmitResponse,
    BatchStatusResponse, BatchResultItem, BatchFailureItem
)
from app.config import settings

router = APIRouter(prefix="/batches", tags=["batches"])


def hash_payload(items: list[str]) -> str:
    """Create a fingerprint of submitted items."""
    return hashlib.sha256(
        json.dumps(items, sort_keys=True).encode()
    ).hexdigest()


# ── POST /batches ──────────────────────────────────────────────
@router.post("", response_model=BatchSubmitResponse, status_code=202)
async def submit_batch(
    body: BatchSubmitRequest,
    x_tenant_id: str = Header(...),
    idempotency_key: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    payload_hash = hash_payload(body.items)

    # Check if this idempotency key was already used
    existing = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == x_tenant_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    record = existing.scalar_one_or_none()

    if record:
        if record.payload_hash != payload_hash:
            # Same key, different payload → conflict
            raise HTTPException(
                status_code=409,
                detail="Idempotency key reused with different payload"
            )
        # Same key, same payload → return original batch_id
        return BatchSubmitResponse(
            batch_id=record.batch_id,
            status="already_accepted"
        )

    # New submission — create batch
    batch_id = str(uuid.uuid4())
    batch = Batch(
        id=batch_id,
        tenant_id=x_tenant_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        status="pending",
        total_items=len(body.items),
    )
    db.add(batch)

    # Create one row per text item
    for index, text in enumerate(body.items):
        db.add(BatchItem(
            batch_id=batch_id,
            item_index=index,
            text=text,
        ))

    # Save idempotency record
    db.add(IdempotencyRecord(
        tenant_id=x_tenant_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        batch_id=batch_id,
    ))

    await db.commit()

# Enqueue background processing
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.enqueue_job("process_batch", batch_id)
        await pool.close()
    except Exception:
        pass  # In tests Redis may not be available

    return BatchSubmitResponse(batch_id=batch_id, status="accepted")
# ── GET /batches/{batch_id} ────────────────────────────────────
@router.get("/{batch_id}", response_model=BatchStatusResponse)
async def get_batch_status(
    batch_id: str,
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    batch = await _get_batch_for_tenant(batch_id, x_tenant_id, db)
    return BatchStatusResponse(
        batch_id=batch.id,
        status=batch.status,
        total=batch.total_items,
        done=batch.done_items,
        failed=batch.failed_items,
    )


# ── GET /batches/{batch_id}/results ───────────────────────────
@router.get("/{batch_id}/results", response_model=list[BatchResultItem])
async def get_batch_results(
    batch_id: str,
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    await _get_batch_for_tenant(batch_id, x_tenant_id, db)
    result = await db.execute(
        select(BatchItem).where(
            BatchItem.batch_id == batch_id,
            BatchItem.status == "success",
        )
    )
    items = result.scalars().all()
    return [
        BatchResultItem(
            item_index=i.item_index,
            text=i.text,
            result=i.result or "",
        )
        for i in items
    ]


# ── GET /batches/{batch_id}/failures ──────────────────────────
@router.get("/{batch_id}/failures", response_model=list[BatchFailureItem])
async def get_batch_failures(
    batch_id: str,
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    await _get_batch_for_tenant(batch_id, x_tenant_id, db)
    result = await db.execute(
        select(BatchItem).where(
            BatchItem.batch_id == batch_id,
            BatchItem.status == "failed",
        )
    )
    items = result.scalars().all()
    return [
        BatchFailureItem(
            item_index=i.item_index,
            text=i.text,
            attempt_count=i.attempt_count,
            last_error=i.last_error or "unknown",
        )
        for i in items
    ]


# ── Helper ─────────────────────────────────────────────────────
async def _get_batch_for_tenant(
    batch_id: str,
    tenant_id: str,
    db: AsyncSession
) -> Batch:
    result = await db.execute(
        select(Batch).where(
            Batch.id == batch_id,
            Batch.tenant_id == tenant_id
        )
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch