import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.database import Base, get_db
from app.models import Batch, BatchItem

# ── Test database setup ────────────────────────────────────────
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_partial.db"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session


# ── Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_partial_failure_status(client, db_session):
    """Batch with some failures shows partially_failed status."""
    # Submit batch
    r = await client.post(
        "/batches",
        json={"items": ["text1", "text2", "text3"]},
        headers={
            "x-tenant-id": "tenant-A",
            "idempotency-key": "key-partial-001"
        }
    )
    batch_id = r.json()["batch_id"]

    # Manually set 2 items success, 1 item failed
    from sqlalchemy import update
    await db_session.execute(
        update(Batch)
        .where(Batch.id == batch_id)
        .values(
            status="partially_failed",
            done_items=2,
            failed_items=1
        )
    )
    await db_session.execute(
        update(BatchItem)
        .where(BatchItem.batch_id == batch_id)
        .values(status="success", result="positive sentiment")
    )
    # Mark one item as failed
    from sqlalchemy import select
    items = await db_session.execute(
        select(BatchItem).where(BatchItem.batch_id == batch_id)
    )
    first_item = items.scalars().first()
    await db_session.execute(
        update(BatchItem)
        .where(BatchItem.id == first_item.id)
        .values(
            status="failed",
            last_error="Server error 500",
            attempt_count=5
        )
    )
    await db_session.commit()

    # Check status
    status_r = await client.get(
        f"/batches/{batch_id}",
        headers={"x-tenant-id": "tenant-A"}
    )
    data = status_r.json()
    assert data["status"] == "partially_failed"
    assert data["done"] == 2
    assert data["failed"] == 1


@pytest.mark.asyncio
async def test_failures_endpoint_returns_details(client, db_session):
    """Failures endpoint returns item details and error."""
    # Submit batch
    r = await client.post(
        "/batches",
        json={"items": ["text1", "text2"]},
        headers={
            "x-tenant-id": "tenant-A",
            "idempotency-key": "key-partial-002"
        }
    )
    batch_id = r.json()["batch_id"]

    # Mark one item as failed manually
    from sqlalchemy import select, update
    items_result = await db_session.execute(
        select(BatchItem).where(BatchItem.batch_id == batch_id)
    )
    first_item = items_result.scalars().first()
    await db_session.execute(
        update(BatchItem)
        .where(BatchItem.id == first_item.id)
        .values(
            status="failed",
            last_error="Server error 500",
            attempt_count=5
        )
    )
    await db_session.commit()

    # Check failures endpoint
    failures_r = await client.get(
        f"/batches/{batch_id}/failures",
        headers={"x-tenant-id": "tenant-A"}
    )
    assert failures_r.status_code == 200
    failures = failures_r.json()
    assert len(failures) == 1
    assert failures[0]["last_error"] == "Server error 500"
    assert failures[0]["attempt_count"] == 5


@pytest.mark.asyncio
async def test_results_available_during_processing(client, db_session):
    """Results endpoint works even while batch is still processing."""
    # Submit batch
    r = await client.post(
        "/batches",
        json={"items": ["text1", "text2", "text3"]},
        headers={
            "x-tenant-id": "tenant-A",
            "idempotency-key": "key-partial-003"
        }
    )
    batch_id = r.json()["batch_id"]

    # Simulate partial completion — only 1 item done
    from sqlalchemy import select, update
    items_result = await db_session.execute(
        select(BatchItem).where(BatchItem.batch_id == batch_id)
    )
    first_item = items_result.scalars().first()
    await db_session.execute(
        update(BatchItem)
        .where(BatchItem.id == first_item.id)
        .values(status="success", result="positive sentiment")
    )
    await db_session.execute(
        update(Batch)
        .where(Batch.id == batch_id)
        .values(status="processing")
    )
    await db_session.commit()

    # Results should be available even though batch is processing
    results_r = await client.get(
        f"/batches/{batch_id}/results",
        headers={"x-tenant-id": "tenant-A"}
    )
    assert results_r.status_code == 200
    results = results_r.json()
    assert len(results) == 1
    assert results[0]["result"] == "positive sentiment"


@pytest.mark.asyncio
async def test_empty_results_when_nothing_done(client):
    """Results endpoint returns empty list when nothing processed yet."""
    r = await client.post(
        "/batches",
        json={"items": ["text1", "text2"]},
        headers={
            "x-tenant-id": "tenant-A",
            "idempotency-key": "key-partial-004"
        }
    )
    batch_id = r.json()["batch_id"]

    results_r = await client.get(
        f"/batches/{batch_id}/results",
        headers={"x-tenant-id": "tenant-A"}
    )
    assert results_r.status_code == 200
    assert results_r.json() == []