from pydantic import BaseModel
from typing import Optional


# ── Request shape — what user SENDS to us ─────────────────────
class BatchSubmitRequest(BaseModel):
    items: list[str]    # array of text strings to analyze


# ── Response shapes — what we SEND BACK to user ───────────────
class BatchSubmitResponse(BaseModel):
    batch_id: str
    status: str


class BatchStatusResponse(BaseModel):
    batch_id: str
    status: str
    total: int
    done: int
    failed: int


class BatchResultItem(BaseModel):
    item_index: int
    text: str
    result: str


class BatchFailureItem(BaseModel):
    item_index: int
    text: str
    attempt_count: int
    last_error: str