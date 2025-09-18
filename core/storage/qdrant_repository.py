"""Qdrant access layer."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional

try:  # pragma: no cover - import is optional for unit tests
    from qdrant_client.http import models as rest
except ImportError:  # pragma: no cover
    from types import SimpleNamespace

    rest = SimpleNamespace(  # type: ignore[var-annotated]
        VectorParams=lambda *args, **kwargs: None,
        Distance=SimpleNamespace(COSINE="Cosine"),
        PointStruct=lambda *args, **kwargs: SimpleNamespace(id="", payload={}, vector=None),
        FieldCondition=lambda *args, **kwargs: None,
        MatchValue=lambda *args, **kwargs: None,
        MatchAny=lambda *args, **kwargs: None,
        Filter=lambda *args, **kwargs: None,
        PointIdsList=lambda *args, **kwargs: None,
        UpdateStatus=SimpleNamespace(COMPLETED="completed"),
    )

from ..models import MemoryHit, MemoryPayload, MemoryRecord


class QdrantRepository:
    """Repository for reading and writing memories in Qdrant."""

    def __init__(self, client: AsyncQdrantClient, collection_name: str, vector_size: int) -> None:
        self._client = client
        self._collection = collection_name
        self._vector_size = vector_size

    async def ensure_collection(self) -> None:
        collections = await self._client.get_collections()
        names = {collection.name for collection in collections.collections}
        if self._collection in names:
            return
        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config=rest.VectorParams(size=self._vector_size, distance=rest.Distance.COSINE),
            on_disk_payload=True,
        )

    async def upsert(self, records: Iterable[MemoryRecord]) -> List[str]:
        points: List[rest.PointStruct] = []
        now = datetime.utcnow().isoformat()
        for record in records:
            payload = record.payload.dict()
            payload.setdefault("updated_at", now)
            payload.setdefault("text", record.text)
            points.append(
                rest.PointStruct(
                    id=record.id,
                    vector=record.vector,
                    payload=payload,
                )
            )
        if not points:
            return []
        await self._client.upsert(collection_name=self._collection, points=points)
        return [point.id for point in points]

    async def search(
        self,
        vector: List[float],
        *,
        limit: int,
        org_id: str,
        agent_id: str,
        scope: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[MemoryHit]:
        must_conditions: List[rest.FieldCondition] = [
            rest.FieldCondition(key="org_id", match=rest.MatchValue(value=org_id)),
            rest.FieldCondition(key="agent_id", match=rest.MatchValue(value=agent_id)),
        ]
        if scope:
            must_conditions.append(rest.FieldCondition(key="scope", match=rest.MatchValue(value=scope)))
        if tags:
            must_conditions.append(
                rest.FieldCondition(key="tags", match=rest.MatchAny(any=tags))
            )

        query_filter = rest.Filter(must=must_conditions)
        search_result = await self._client.search(
            collection_name=self._collection,
            query_vector=vector,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
            limit=limit,
            score_threshold=None,
        )
        hits: List[MemoryHit] = []
        for point in search_result:
            payload = MemoryPayload.model_validate(point.payload)
            hits.append(
                MemoryHit(
                    id=str(point.id),
                    score=point.score,
                    text=payload.text,
                    payload=payload,
                )
            )
        return hits

    async def get(self, memory_id: str) -> Optional[MemoryRecord]:
        response = await self._client.retrieve(
            collection_name=self._collection,
            ids=[memory_id],
            with_vectors=False,
            with_payload=True,
        )
        if not response:
            return None
        point = response[0]
        payload = MemoryPayload.model_validate(point.payload)
        text = point.payload.get("text", "")
        return MemoryRecord(id=str(point.id), text=text, payload=payload)

    async def delete(self, memory_id: str) -> bool:
        operation = await self._client.delete(
            collection_name=self._collection,
            points_selector=rest.PointIdsList(points=[memory_id]),
        )
        return operation.status == rest.UpdateStatus.COMPLETED

    async def set_payload(self, record: MemoryRecord) -> None:
        payload = record.payload.dict()
        payload.setdefault("text", record.text)
        await self._client.set_payload(
            collection_name=self._collection,
            payload=payload,
            points=[record.id],
        )

    async def soft_delete(self, memory_id: str) -> bool:
        record = await self.get(memory_id)
        if not record:
            return False
        record.payload.deleted = True
        record.payload.updated_at = datetime.utcnow()
        await self.set_payload(record)
        return True

    async def find_by_hash(self, dedupe_hash: str, org_id: str, agent_id: str) -> Optional[MemoryRecord]:
        query_filter = rest.Filter(
            must=[
                rest.FieldCondition(key="org_id", match=rest.MatchValue(value=org_id)),
                rest.FieldCondition(key="agent_id", match=rest.MatchValue(value=agent_id)),
                rest.FieldCondition(key="dedupe_hash", match=rest.MatchValue(value=dedupe_hash)),
            ]
        )
        points, _ = await self._client.scroll(
            collection_name=self._collection,
            scroll_filter=query_filter,
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return None
        point = points[0]
        payload = MemoryPayload.model_validate(point.payload)
        text = payload.text
        return MemoryRecord(id=str(point.id), text=text, payload=payload)
