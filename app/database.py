from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

# Create async engine — this is the connection to PostgreSQL
engine = create_async_engine(settings.database_url, echo=True)

# Session factory — creates a new session every time we need to talk to DB
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Base class — all our database models will inherit from this
class Base(DeclarativeBase):
    pass

# Dependency — used in API endpoints to get a DB session
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session