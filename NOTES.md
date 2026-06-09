# Notes

## What I Used AI For
- Used Claude AI assistant to help scaffold the project structure
- All code reviewed and understood line by line
- All design decisions are my own

## What I'm Proud Of
- Strict idempotency at both batch and item level
- Atomic Redis Lua script for rate limiting
- Clean partial failure visibility
- All 14 tests passing
- Full docker compose setup with 5 services

## What I Would Do Differently With More Time
- Add pagination to results and failures endpoints
- Add webhook support for batch completion notification
- Make rate limit config per-tenant from database
- Add proper structured logging with correlation IDs
- Add Prometheus metrics endpoint
- Use Alembic for proper database migrations instead of create_all
- Add request timeout handling

## What I Cut
- Real OAuth authentication (used X-Tenant-ID header instead)
- Pagination (not required per spec)
- Webhooks (not required per spec)
- Production database migrations

## Known Issues
- Since no starter repo was provided with the assignment PDF,
  I built my own mock third party API in mock_api/ folder
- The mock API runs on port 8081 externally (8080 internally)
  due to port conflict on development machine
- datetime.utcnow() deprecation warning in tests
  (harmless, will fix with datetime.now(UTC) in future)

## Time Spent
- Setup and Docker: ~1 hour
- Database models and API endpoints: ~1.5 hours
- Rate limiter and worker: ~1.5 hours
- Mock API and integration: ~1 hour
- Tests: ~1 hour
- Total: ~6 hours