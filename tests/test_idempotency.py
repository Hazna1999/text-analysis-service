import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.database import Base, get_db

# ── Test database setup ────────────────────────────────────────
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

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


# ── Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_batch_success(client):
    """New batch submission returns accepted."""
    response = await client.post(
        "/batches",
        json={"items": ["text1", "text2"]},
        headers={
            "x-tenant-id": "tenant-A",
            "idempotency-key": "key-001"
        }
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    assert "batch_id" in data


@pytest.mark.asyncio
async def test_idempotency_same_payload(client):
    """Same key + same payload returns original batch_id."""
    payload = {"items": ["text1", "text2"]}
    headers = {
        "x-tenant-id": "tenant-A",
        "idempotency-key": "key-002"
    }

    # First submission
    r1 = await client.post("/batches", json=payload, headers=headers)
    assert r1.status_code == 202
    batch_id_1 = r1.json()["batch_id"]

    # Second submission — same key same payload
    r2 = await client.post("/batches", json=payload, headers=headers)
    assert r2.status_code == 202
    assert r2.json()["batch_id"] == batch_id_1
    assert r2.json()["status"] == "already_accepted"


@pytest.mark.asyncio
async def test_idempotency_different_payload_returns_409(client):
    """Same key + different payload returns 409 conflict."""
    headers = {
        "x-tenant-id": "tenant-A",
        "idempotency-key": "key-003"
    }

    # First submission
    await client.post(
        "/batches",
        json={"items": ["original text"]},
        headers=headers
    )

    # Second submission — same key different payload
    response = await client.post(
        "/batches",
        json={"items": ["completely different text"]},
        headers=headers
    )
    assert response.status_code == 409
    assert "different payload" in response.json()["detail"]


@pytest.mark.asyncio
async def test_tenant_isolation(client):
    """Tenant A cannot see Tenant B batches."""
    # Tenant A submits batch
    r = await client.post(
        "/batches",
        json={"items": ["text1"]},
        headers={
            "x-tenant-id": "tenant-A",
            "idempotency-key": "key-004"
        }
    )
    batch_id = r.json()["batch_id"]

    # Tenant B tries to access Tenant A batch
    response = await client.get(
        f"/batches/{batch_id}",
        headers={"x-tenant-id": "tenant-B"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_batch_status_after_submit(client):
    """Batch status is pending right after submission."""
    r = await client.post(
        "/batches",
        json={"items": ["text1", "text2", "text3"]},
        headers={
            "x-tenant-id": "tenant-A",
            "idempotency-key": "key-005"
        }
    )
    batch_id = r.json()["batch_id"]

    # Check status
    status_r = await client.get(
        f"/batches/{batch_id}",
        headers={"x-tenant-id": "tenant-A"}
    )
    assert status_r.status_code == 200
    data = status_r.json()
    assert data["total"] == 3
    assert data["status"] == "pending"