"""Core service orchestrating memory ingest and retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    from qdrant_client import AsyncQdrantClient
except ImportError:  # pragma: no cover - allows unit tests without qdrant installed
    class AsyncQdrantClient:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401
            """Fallback stub used in testing environments."""

        async def close(self) -> None:  # type: ignore[empty-body]
            return None

from .clients import OpenRouterClient, TEIClient
from .config.models import CollectionPolicy, OrgConfig, Settings, TenantOverrides
from .exceptions import NotFoundError
from .models import (
    MemoryAddRequest,
    MemoryHit,
    MemoryPayload,
    MemoryRecord,
    MemoryScope,
    SearchRequest,
    UpdateMemoryRequest,
)
from .policies import WritePolicyEngine
from .storage import QdrantRepository
from .utils import apply_time_decay, compute_hash, make_id


class MemoryCore:
    """High-level orchestration of the memory workflow."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        services = settings.services
        self._tei = TEIClient(str(services.tei_base_url))
        self._llm = OpenRouterClient(
            api_key=services.openrouter_api_key,
            base_url=str(services.openrouter_base_url),
            model=settings.core.model,
        )
        self._qdrant_client = AsyncQdrantClient(
            url=str(services.qdrant_url), api_key=services.qdrant_api_key
        )
        self._repositories: Dict[Tuple[str, int], QdrantRepository] = {}
        base_collection = settings.core.collection
        if services.qdrant_collection and services.qdrant_collection != base_collection.name:
            base_collection = CollectionPolicy(
                name=services.qdrant_collection,
                vector_size=base_collection.vector_size,
                distance=base_collection.distance,
                on_disk_payload=base_collection.on_disk_payload,
            )
        self._default_collection = base_collection

    async def startup(self) -> None:
        await self._ensure_repository(self._default_collection)

    async def shutdown(self) -> None:
        await self._tei.close()
        await self._llm.close()
        await self._qdrant_client.close()

    # ------------------------------------------------------------------
    # Configuration helpers

    async def _ensure_repository(self, policy: CollectionPolicy) -> QdrantRepository:
        key = (policy.name, policy.vector_size)
        if key not in self._repositories:
            self._repositories[key] = QdrantRepository(
                client=self._qdrant_client,
                collection_name=policy.name,
                vector_size=policy.vector_size,
            )
        repo = self._repositories[key]
        await repo.ensure_collection()
        return repo

    async def _get_repository(self, overrides: TenantOverrides) -> QdrantRepository:
        collection = overrides.collection or self._default_collection
        return await self._ensure_repository(collection)

    def _resolve_overrides(self, org_id: str, agent_id: Optional[str]) -> TenantOverrides:
        core = self._settings.core
        org_config: Optional[OrgConfig] = core.organisations.get(org_id)
        if not org_config:
            return TenantOverrides()
        # Start with org-level overrides
        resolved = TenantOverrides(
            write=org_config.write,
            retrieval=org_config.retrieval,
            collection=org_config.collection,
            model=org_config.model,
            embedding_dims=org_config.embedding_dims,
        )
        if agent_id and agent_id in org_config.agents:
            agent = org_config.agents[agent_id]
            resolved.write = agent.write or resolved.write
            resolved.retrieval = agent.retrieval or resolved.retrieval
            resolved.collection = agent.collection or resolved.collection
            resolved.model = agent.model or resolved.model
            resolved.embedding_dims = agent.embedding_dims or resolved.embedding_dims
        return resolved

    def _build_policy_engine(self, overrides: TenantOverrides) -> WritePolicyEngine:
        write_policy = overrides.write or self._settings.core.write
        return WritePolicyEngine(write_policy)

    def _resolve_top_k(self, overrides: TenantOverrides) -> int:
        retrieval = overrides.retrieval or self._settings.core.retrieval
        return retrieval.top_k

    # ------------------------------------------------------------------
    # Public API

    async def add(self, org_id: str, agent_id: str, request: MemoryAddRequest) -> List[MemoryRecord]:
        overrides = self._resolve_overrides(org_id, agent_id)
        repository = await self._get_repository(overrides)
        policy_engine = self._build_policy_engine(overrides)

        candidate_texts = [text.strip() for text in request.iter_texts() if text.strip()]
        if not candidate_texts:
            return []

        model_name = overrides.model or self._settings.core.model
        if policy_engine.normalize_with_llm:
            candidate_texts = await self._llm.normalize_memories(candidate_texts, model=model_name)

        texts = [
            text for text in candidate_texts if policy_engine.should_persist(text, request.scope or MemoryScope.FACTS.value)
        ]
        if not texts:
            return []

        new_records: List[MemoryRecord] = []
        all_records: List[MemoryRecord] = []
        vectors = await self._tei.embed(texts)

        for text, vector in zip(texts, vectors):
            memory_id = make_id(org_id, agent_id, text)
            dedupe_hash = compute_hash(org_id, agent_id, request.user_id, text)
            if policy_engine.deduplicate:
                existing = await repository.find_by_hash(dedupe_hash, org_id, agent_id)
                if existing:
                    all_records.append(existing)
                    continue
            payload = MemoryPayload(
                org_id=org_id,
                agent_id=agent_id,
                user_id=request.user_id,
                scope=request.scope or MemoryScope.FACTS.value,
                tags=request.tags,
                source=request.source,
                ttl_days=request.ttl_days,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                text=text,
                dedupe_hash=dedupe_hash,
            )
            record = MemoryRecord(id=memory_id, text=text, payload=payload, vector=vector)
            new_records.append(record)
            all_records.append(record)

        if new_records:
            await repository.upsert(new_records)
        return all_records

    async def search(
        self,
        org_id: str,
        agent_id: str,
        request: SearchRequest,
    ) -> List[MemoryHit]:
        overrides = self._resolve_overrides(org_id, agent_id)
        repository = await self._get_repository(overrides)
        top_k = request.k or self._resolve_top_k(overrides)
        vector = (await self._tei.embed([request.query]))[0]
        hits = await repository.search(
            vector,
            limit=top_k,
            org_id=org_id,
            agent_id=agent_id,
            scope=request.scope,
            tags=request.tags or None,
        )
        now = datetime.utcnow()
        adjusted: List[MemoryHit] = []
        for hit in hits:
            payload = hit.payload
            score = apply_time_decay(hit.score, payload.created_at, now)
            adjusted.append(MemoryHit(id=hit.id, score=score, text=hit.text, payload=payload))
        adjusted.sort(key=lambda h: h.score, reverse=True)
        return adjusted

    async def update(self, org_id: str, agent_id: str, memory_id: str, request: UpdateMemoryRequest) -> MemoryRecord:
        repository = await self._get_repository(self._resolve_overrides(org_id, agent_id))
        record = await repository.get(memory_id)
        if not record:
            raise NotFoundError("memory not found")
        payload = record.payload
        if payload.org_id != org_id or payload.agent_id != agent_id:
            raise NotFoundError("memory not found")

        if request.text:
            record.text = request.text
        if request.tags is not None:
            payload.tags = request.tags
        if request.scope is not None:
            payload.scope = request.scope
        if request.ttl_days is not None:
            payload.ttl_days = request.ttl_days
        if request.deleted is not None:
            payload.deleted = request.deleted
        payload.updated_at = datetime.utcnow()
        payload.text = record.text

        if request.text:
            vector = (await self._tei.embed([record.text]))[0]
            record.vector = vector
            await repository.upsert([record])
        else:
            await repository.set_payload(record)
        return record

    async def delete(self, org_id: str, agent_id: str, memory_id: str, *, hard: bool = False) -> None:
        repository = await self._get_repository(self._resolve_overrides(org_id, agent_id))
        record = await repository.get(memory_id)
        if not record:
            raise NotFoundError("memory not found")
        payload = record.payload
        if payload.org_id != org_id or payload.agent_id != agent_id:
            raise NotFoundError("memory not found")
        if hard:
            await repository.delete(memory_id)
        else:
            await repository.soft_delete(memory_id)

    async def list(
        self,
        org_id: str,
        agent_id: str,
        *,
        limit: int,
        include_deleted: bool = False,
    ) -> List[MemoryRecord]:
        repository = await self._get_repository(self._resolve_overrides(org_id, agent_id))
        records = await repository.list_recent(org_id, agent_id, limit=limit, include_deleted=include_deleted)
        return records

    async def get_many(
        self,
        org_id: str,
        agent_id: str,
        memory_ids: List[str],
    ) -> List[MemoryRecord]:
        repository = await self._get_repository(self._resolve_overrides(org_id, agent_id))
        records = await repository.get_many(memory_ids)
        filtered = [record for record in records if record.payload.org_id == org_id and record.payload.agent_id == agent_id]
        return filtered

    async def delete_many(
        self,
        org_id: str,
        agent_id: str,
        memory_ids: List[str],
        *,
        hard: bool = False,
    ) -> None:
        if not memory_ids:
            return
        repository = await self._get_repository(self._resolve_overrides(org_id, agent_id))
        if hard:
            await repository.delete_many(memory_ids)
            return
        records = await repository.get_many(memory_ids)
        for record in records:
            if record.payload.org_id == org_id and record.payload.agent_id == agent_id:
                record.payload.deleted = True
                record.payload.updated_at = datetime.utcnow()
                await repository.set_payload(record)

    async def search_text(
        self,
        org_id: str,
        agent_id: str,
        query: str,
        *,
        limit: int,
        include_deleted: bool = False,
    ) -> List[MemoryRecord]:
        repository = await self._get_repository(self._resolve_overrides(org_id, agent_id))
        records = await repository.search_text(
            org_id,
            agent_id,
            query,
            limit=limit,
            include_deleted=include_deleted,
        )
        return records
