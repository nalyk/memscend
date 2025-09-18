"""Domain models for the memory service."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Iterable, List, Optional

from pydantic import BaseModel, Field

DEFAULT_TTL_DAYS = 365


class MemoryScope(str, Enum):
    """Supported memory scopes."""

    PREFS = "prefs"
    FACTS = "facts"
    PERSONA = "persona"
    CONSTRAINTS = "constraints"

    @classmethod
    def list(cls) -> List[str]:
        return [item.value for item in cls]


class MemoryPayload(BaseModel):
    """Metadata stored alongside embeddings."""

    org_id: str
    agent_id: str
    user_id: str
    scope: str = Field(default=MemoryScope.FACTS.value)
    tags: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    deleted: bool = False
    text: str = ""
    dedupe_hash: Optional[str] = None

    model_config = {
        "extra": "ignore",
    }


class MemoryRecord(BaseModel):
    """Full representation of a stored memory."""

    id: str
    text: str
    payload: MemoryPayload
    vector: Optional[List[float]] = None


class MemoryHit(BaseModel):
    """Result entry returned from semantic search."""

    id: str
    score: float
    text: str
    payload: MemoryPayload


class MemoryAddItem(BaseModel):
    """Request item representing a candidate memory entry."""

    text: str
    scope: str = MemoryScope.FACTS.value
    tags: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    ttl_days: int = DEFAULT_TTL_DAYS


class MemoryAddRequest(BaseModel):
    """Payload accepted by the add memories endpoint."""

    user_id: str
    messages: Optional[List[dict]] = None
    text: Optional[str] = None
    scope: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    source: Optional[str] = None
    ttl_days: int = DEFAULT_TTL_DAYS

    def iter_texts(self) -> Iterable[str]:
        if self.text:
            yield self.text
        if self.messages:
            for message in self.messages:
                content = message.get("content")
                if content:
                    yield content


class SearchRequest(BaseModel):
    """Parameters for searching memories."""

    query: str
    user_id: Optional[str] = None
    k: int = 6
    scope: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class UpdateMemoryRequest(BaseModel):
    """Patch request for a stored memory."""

    text: Optional[str] = None
    tags: Optional[List[str]] = None
    scope: Optional[str] = None
    ttl_days: Optional[int] = Field(default=None, ge=1)
    deleted: Optional[bool] = None


class DeleteMemoryRequest(BaseModel):
    """Request model for deletions."""

    hard: bool = False
