import asyncio
import random
import logging
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Mock Third Party Analysis API")


class AnalyzeRequest(BaseModel):
    id: str
    text: str


class AnalyzeResponse(BaseModel):
    id: str
    result: str


@app.post("/v1/analyze", response_model=AnalyzeResponse)
async def analyze(
    body: AnalyzeRequest,
    x_api_key: str = Header(...),
):
    # Simulate random delay
    delay = random.uniform(0.1, 2.0)
    await asyncio.sleep(delay)

    # Simulate random failures
    roll = random.random()

    if roll < 0.15:
        # 15% chance → 500 server error
        logger.warning(f"Simulating 500 for item {body.id}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )

    elif roll < 0.25:
        # 10% chance → 429 rate limited
        logger.warning(f"Simulating 429 for item {body.id}")
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "3"},
            content={"detail": "Rate limit exceeded"},
        )

    # 75% chance → success
    sentiments = ["positive", "negative", "neutral", "mixed"]
    result = f"{random.choice(sentiments)} sentiment detected"
    logger.info(f"Success for item {body.id}: {result}")

    return AnalyzeResponse(id=body.id, result=result)


@app.get("/health")
async def health():
    return {"status": "ok", "message": "Mock API running"}