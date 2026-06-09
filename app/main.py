from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.database import engine, Base
from app.routers import batches
import app.models

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all database tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(title="Text Analysis Service", lifespan=lifespan)

# Register routes
app.include_router(batches.router)

@app.get("/health")
async def health():
    return {"status": "ok", "message": "Server is running!"}