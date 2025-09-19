from __future__ import annotations

from datetime import datetime, timedelta
from typing import List
from unittest.mock import AsyncMock

import pytest

from core.config.models import CoreConfig, ExternalServiceConfig, SecurityConfig, Settings
from core.models import MemoryAddRequest, MemoryHit, MemoryPayload, MemoryRecord, SearchRequest
from core.services import MemoryCore


class StubRepository:
    def __init__(self) -> None:
        self.by_hash: dict[str, MemoryRecord] = {}
        self.upsert_calls: List[List[MemoryRecord]] = []
        self.search_results: List[MemoryHit] = []

    async def ensure_collection(self) -> None:  # pragma: no cover - not used in unit
        return None

    async def find_by_hash(self, dedupe_hash: str, org_id: str, agent_id: str) -> MemoryRecord | None:
        return self.by_hash.get(dedupe_hash)

    async def upsert(self, records: List[MemoryRecord]) -> List[str]:
        self.upsert_calls.append(records)
        for record in records:
            if record.payload.dedupe_hash:
                self.by_hash[record.payload.dedupe_hash] = record
        return [record.id for record in records]

    async def search(self, vector: List[float], *, limit: int, org_id: str, agent_id: str, scope=None, tags=None):
        return self.search_results[:limit]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        services=ExternalServiceConfig(
            openrouter_api_key="key",
            openrouter_base_url="https://example.com",
            tei_base_url="https://tei",
            qdrant_url="https://qdrant",
            qdrant_collection="memories",
        ),
        core=CoreConfig(),
        security=SecurityConfig(shared_secrets={}),
    )


@pytest.mark.asyncio
async def test_add_deduplicates_memories(settings: Settings):
    core = MemoryCore(settings)
    repo = StubRepository()

    async def fake_get_repository(overrides):
        return repo

    core._get_repository = fake_get_repository  # type: ignore[attr-defined]
    core._tei.embed = AsyncMock(return_value=[[0.1] * 768])  # type: ignore[assignment]
    core._llm.normalize_memories = AsyncMock(side_effect=lambda texts, model=None: texts)  # type: ignore[assignment]

    request = MemoryAddRequest(user_id="user-1", text="Call mom tomorrow", scope="prefs")

    first = await core.add("org-1", "agent-1", request)
    assert len(first) == 1
    assert len(repo.upsert_calls) == 1

    second = await core.add("org-1", "agent-1", request)
    assert len(second) == 1
    # No new upsert because the memory was deduplicated
    assert len(repo.upsert_calls) == 1


@pytest.mark.asyncio
async def test_search_applies_time_decay(settings: Settings):
    core = MemoryCore(settings)
    repo = StubRepository()

    async def fake_get_repository(overrides):
        return repo

    core._get_repository = fake_get_repository  # type: ignore[attr-defined]
    core._tei.embed = AsyncMock(return_value=[[0.2] * 768])  # type: ignore[assignment]

    recent_payload = MemoryPayload(
        org_id="org-1",
        agent_id="agent-1",
        user_id="user-9",
        scope="prefs",
        tags=[],
        text="Recent",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    old_payload = MemoryPayload(
        org_id="org-1",
        agent_id="agent-1",
        user_id="user-9",
        scope="prefs",
        tags=[],
        text="Old",
        created_at=datetime.utcnow() - timedelta(days=180),
        updated_at=datetime.utcnow() - timedelta(days=180),
    )

    repo.search_results = [
        MemoryHit(id="recent", score=0.5, text="Recent", payload=recent_payload),
        MemoryHit(id="old", score=0.9, text="Old", payload=old_payload),
    ]

    results = await core.search("org-1", "agent-1", SearchRequest(query="prefs"))
    assert [hit.id for hit in results] == ["recent", "old"], "recent record should outrank after decay"
