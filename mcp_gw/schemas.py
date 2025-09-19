"""Pydantic models used by the MCP gateway."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Protocol

if TYPE_CHECKING:  # pragma: no cover - import-time cycle guard
    from core.models import MemoryHit, MemoryPayload, MemoryRecord

from pydantic import BaseModel, Field


class MemoryPayloadView(BaseModel):
    """Serializable payload returned to MCP clients."""

    org_id: str
    agent_id: str
    user_id: str
    scope: str
    tags: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    ttl_days: int
    created_at: datetime
    updated_at: datetime
    deleted: bool = False
    text: str
    dedupe_hash: Optional[str] = None

    model_config = {"from_attributes": True}


class MemoryItemView(BaseModel):
    """Memory record representation shared across responses."""

    id: str
    text: str
    payload: MemoryPayloadView

    model_config = {"from_attributes": True}

    @classmethod
    def from_record(
        cls, record: "MemoryRecord | MemoryRecordProtocol"
    ) -> "MemoryItemView":
        return cls(
            id=record.id,
            text=record.text,
            payload=MemoryPayloadView.model_validate(record.payload),
        )


class MemoryHitView(MemoryItemView):
    """Search hit that includes a relevance score."""

    score: float

    @classmethod
    def from_hit(
        cls, hit: "MemoryHit | MemoryHitProtocol"
    ) -> "MemoryHitView":
        return cls(
            id=hit.id,
            text=hit.text,
            payload=MemoryPayloadView.model_validate(hit.payload),
            score=hit.score,
        )


class AddMemoriesResponse(BaseModel):
    """Structured response emitted by the add tool."""

    items: List[MemoryItemView] = Field(default_factory=list)


class SearchMemoryResponse(BaseModel):
    """Structured response emitted by the search tool."""

    hits: List[MemoryHitView] = Field(default_factory=list)


class UpdateMemoryResponse(BaseModel):
    """Structured response emitted by the update tool."""

    record: MemoryItemView


class DeleteMemoryResponse(BaseModel):
    """Structured response emitted by the delete tool."""

    ok: bool
    reason: Optional[str] = None


class CapabilitiesResource(BaseModel):
    """Static capability metadata exposed as an MCP resource."""

    name: str
    version: str
    transports: List[str]
    enabled_scopes: List[str]
    default_top_k: int
    vector_size: int
    normalize_with_llm: bool


class MemoryRecordProtocol(Protocol):
    """Structural type used to ease cross-package imports."""

    id: str
    text: str
    payload: "MemoryPayload"


class MemoryHitProtocol(MemoryRecordProtocol, Protocol):
    """Structural type used to ease cross-package imports."""

    score: float
