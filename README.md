# Text Analysis Service

A multi-tenant SaaS backend for high-throughput text analysis.

## How to Run

```bash
docker compose up --build
```

API will be available at http://localhost:8001

## How to Call the API

### Submit a batch
```bash
curl -X POST http://localhost:8001/batches \
  -H "Content-Type: application/json" \
  -H "x-tenant-id: company-A" \
  -H "idempotency-key: unique-key-001" \
  -d '{"items": ["text one", "text two", "text three"]}'
```

### Check batch status
```bash
curl http://localhost:8001/batches/{batch_id} \
  -H "x-tenant-id: company-A"
```

### Get results
```bash
curl http://localhost:8001/batches/{batch_id}/results \
  -H "x-tenant-id: company-A"
```

### Get failures
```bash
curl http://localhost:8001/batches/{batch_id}/failures \
  -H "x-tenant-id: company-A"
```

## Design Notes

### Architecture
- **FastAPI** — async web framework for API endpoints
- **PostgreSQL** — durable storage for batches, items, results
- **Redis** — token bucket rate limiting + Arq job queue
- **Arq** — async background worker for batch processing
- **Mock API** — fake third party API in mock_api/ folder

### Idempotency
- Batch level: same Idempotency-Key + same payload returns original batch_id
- Same key + different payload returns 409 Conflict
- Item level: workers check item status before processing to prevent double processing

### Rate Limiting
- Per-tenant Redis token bucket implemented with Lua script
- Atomic — works correctly across multiple worker processes
- Default: 100 token capacity, 10 tokens/second refill rate

### Resilience
- Capped concurrency via asyncio Semaphore (default 10)
- Exponential backoff with jitter on failures
- 429 responses respect Retry-After header
- Max 5 retries before marking item as permanently failed
- Partial failures resolve to partially_failed status

## Run Tests

```bash
pip install aiosqlite greenlet
python3.12 -m pytest tests/ -v
```