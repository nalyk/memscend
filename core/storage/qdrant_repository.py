"""Qdrant access layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from qdrant_client import AsyncQdrantClient
else:  # pragma: no cover - runtime fallback when qdrant isn't installed
    AsyncQdrantClient = Any  # type: ignore[assignment]

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
        OrderBy=lambda *args, **kwargs: None,
        OrderByKind=SimpleNamespace(ASC="asc", DESC="desc"),
        KeywordIndexParams=lambda *args, **kwargs: None,
        BoolIndexParams=lambda *args, **kwargs: None,
        DatetimeIndexParams=lambda *args, **kwargs: None,
        KeywordIndexType=SimpleNamespace(KEYWORD="keyword"),
        BoolIndexType=SimpleNamespace(BOOL="bool"),
        DatetimeIndexType=SimpleNamespace(DATETIME="datetime"),
        Prefetch=lambda *args, **kwargs: SimpleNamespace(**kwargs),
        NearestQuery=lambda *args, **kwargs: SimpleNamespace(**kwargs),
        FormulaQuery=lambda *args, **kwargs: SimpleNamespace(**kwargs),
        MultExpression=lambda *args, **kwargs: SimpleNamespace(**kwargs),
        GaussDecayExpression=lambda *args, **kwargs: SimpleNamespace(**kwargs),
        DecayParamsExpression=lambda *args, **kwargs: SimpleNamespace(**kwargs),
        DatetimeKeyExpression=lambda *args, **kwargs: SimpleNamespace(**kwargs),
        DatetimeExpression=lambda *args, **kwargs: SimpleNamespace(**kwargs),
    )

from ..models import MemoryHit, MemoryPayload, MemoryRecord
from ..utils import TIME_DECAY_HALF_LIFE_DAYS


class QdrantRepository:
    """Repository for reading and writing memories in Qdrant."""

    def __init__(self, client: AsyncQdrantClient, collection_name: str, vector_size: int) -> None:
        self._client = client
        self._collection = collection_name
        self._vector_size = vector_size
        self._reranker_available: Optional[bool] = None
        self._time_decay_half_life_days = TIME_DECAY_HALF_LIFE_DAYS

    async def ensure_collection(self) -> None:
        """Ensure the default collection and required payload indexes exist."""

        collections = await self._client.get_collections()
        names = {collection.name for collection in collections.collections}
        if self._collection not in names:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=rest.VectorParams(
                    size=self._vector_size,
                    distance=rest.Distance.COSINE,
                ),
                on_disk_payload=True,
            )

        await self._ensure_payload_indexes()

    async def _ensure_payload_indexes(self) -> None:
        """Create the payload indexes needed for multi-tenant filtering."""

        try:
            collection_info = await self._client.get_collection(collection_name=self._collection)
            existing_schema = getattr(collection_info, "payload_schema", {}) or {}
        except Exception:  # pragma: no cover - network/client errors bubble later
            existing_schema = {}

        keyword_type = getattr(getattr(rest, "KeywordIndexType", None), "KEYWORD", "keyword")
        bool_type = getattr(getattr(rest, "BoolIndexType", None), "BOOL", "bool")
        datetime_type = getattr(getattr(rest, "DatetimeIndexType", None), "DATETIME", "datetime")

        required_indexes = {
            "org_id": rest.KeywordIndexParams(type=keyword_type, is_tenant=True),
            "agent_id": rest.KeywordIndexParams(type=keyword_type),
            "user_id": rest.KeywordIndexParams(type=keyword_type),
            "scope": rest.KeywordIndexParams(type=keyword_type),
            "tags": rest.KeywordIndexParams(type=keyword_type),
            "dedupe_hash": rest.KeywordIndexParams(type=keyword_type),
            "deleted": getattr(rest, "BoolIndexParams", lambda **_: None)(type=bool_type),
            "created_at": getattr(rest, "DatetimeIndexParams", lambda **_: None)(type=datetime_type),
            "updated_at": getattr(rest, "DatetimeIndexParams", lambda **_: None)(type=datetime_type),
        }

        for field_name, schema in required_indexes.items():
            if schema is None:
                continue

            if isinstance(existing_schema, dict) and field_name in existing_schema:
                current = existing_schema[field_name]
                if field_name == "org_id":
                    if self._has_tenant_flag(current):
                        continue
                    try:
                        await self._client.delete_payload_index(
                            collection_name=self._collection,
                            field_name=field_name,
                        )
                    except Exception:  # pragma: no cover - index removal best effort
                        pass
                else:
                    continue

            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field_name,
                field_schema=schema,
            )

    def _build_filter(
        self,
        org_id: str,
        agent_id: str,
        *,
        scope: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> rest.Filter:
        conditions: List[rest.FieldCondition] = [
            rest.FieldCondition(key="org_id", match=rest.MatchValue(value=org_id)),
            rest.FieldCondition(key="agent_id", match=rest.MatchValue(value=agent_id)),
        ]
        if scope:
            conditions.append(rest.FieldCondition(key="scope", match=rest.MatchValue(value=scope)))
        if tags:
            conditions.append(rest.FieldCondition(key="tags", match=rest.MatchAny(any=tags)))
        return rest.Filter(must=conditions)

    async def search_with_reranker(
        self,
        vector: List[float],
        *,
        limit: int,
        org_id: str,
        agent_id: str,
        scope: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[List[MemoryHit]]:
        """Use Qdrant's formula queries to blend semantic score with recency."""

        if self._reranker_available is False:
            return None

        required_attrs = (
            "Prefetch",
            "NearestQuery",
            "FormulaQuery",
            "MultExpression",
            "GaussDecayExpression",
            "DecayParamsExpression",
            "DatetimeKeyExpression",
            "DatetimeExpression",
        )
        if any(not hasattr(rest, attr) for attr in required_attrs):
            self._reranker_available = False
            return None

        query_filter = self._build_filter(org_id, agent_id, scope=scope, tags=tags)
        now_iso = datetime.utcnow().isoformat()
        half_life_seconds = float(self._time_decay_half_life_days * 24 * 60 * 60)
        prefetch_limit = max(limit * 4, max(limit, 1))
        prefetch_limit = min(prefetch_limit, 128)

        try:
            response = await self._client.query_points(
                collection_name=self._collection,
                prefetch=rest.Prefetch(
                    query=rest.NearestQuery(nearest=vector),
                    filter=query_filter,
                    limit=prefetch_limit,
                ),
                query=rest.FormulaQuery(
                    formula=rest.MultExpression(
                        mult=[
                            "$score",
                            rest.GaussDecayExpression(
                                gauss_decay=rest.DecayParamsExpression(
                                    x=rest.DatetimeKeyExpression(datetime_key="created_at"),
                                    target=rest.DatetimeExpression(datetime=now_iso),
                                    scale=half_life_seconds,
                                )
                            ),
                        ]
                    )
                ),
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
                limit=limit,
            )
        except Exception:  # pragma: no cover - fall back to classic search path
            self._reranker_available = False
            return None

        self._reranker_available = True
        hits: List[MemoryHit] = []
        for point in response.points:
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

    @staticmethod
    def _has_tenant_flag(schema: object) -> bool:
        """Return True if the existing schema already marks the field as tenant-aware."""

        if hasattr(schema, "params"):
            keyword_params = getattr(schema.params, "keyword_index_params", None)
            if keyword_params and getattr(keyword_params, "is_tenant", False):
                return True

        if isinstance(schema, dict):
            params = schema.get("params") or {}
            keyword_params = params.get("keyword_index_params") or {}
            return bool(keyword_params.get("is_tenant"))

        return False

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
        query_filter = self._build_filter(org_id, agent_id, scope=scope, tags=tags)
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

    async def delete_many(self, memory_ids: List[str]) -> bool:
        if not memory_ids:
            return True
        operation = await self._client.delete(
            collection_name=self._collection,
            points_selector=rest.PointIdsList(points=memory_ids),
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

    async def get_many(self, memory_ids: List[str]) -> List[MemoryRecord]:
        if not memory_ids:
            return []
        response = await self._client.retrieve(
            collection_name=self._collection,
            ids=memory_ids,
            with_vectors=False,
            with_payload=True,
        )
        records: List[MemoryRecord] = []
        for point in response:
            payload = MemoryPayload.model_validate(point.payload)
            text = payload.text
            records.append(MemoryRecord(id=str(point.id), text=text, payload=payload))
        return records

    async def list_recent(
        self,
        org_id: str,
        agent_id: str,
        *,
        limit: int,
        include_deleted: bool = False,
    ) -> List[MemoryRecord]:
        conditions: List[rest.FieldCondition] = [
            rest.FieldCondition(key="org_id", match=rest.MatchValue(value=org_id)),
            rest.FieldCondition(key="agent_id", match=rest.MatchValue(value=agent_id)),
        ]
        if not include_deleted:
            conditions.append(rest.FieldCondition(key="deleted", match=rest.MatchValue(value=False)))

        order_by = None
        if hasattr(rest, "OrderBy") and hasattr(rest, "OrderByKind"):
            order_by = [rest.OrderBy(key="updated_at", direction=rest.OrderByKind.DESC)]

        points, _ = await self._client.scroll(
            collection_name=self._collection,
            scroll_filter=rest.Filter(must=conditions),
            limit=limit,
            with_vectors=False,
            with_payload=True,
            order_by=order_by,
        )

        records: List[MemoryRecord] = []
        for point in points:
            payload = MemoryPayload.model_validate(point.payload)
            text = payload.text
            records.append(MemoryRecord(id=str(point.id), text=text, payload=payload))
        return records

    async def search_text(
        self,
        org_id: str,
        agent_id: str,
        query: str,
        *,
        limit: int,
        include_deleted: bool = False,
    ) -> List[MemoryRecord]:
        needle = query.lower()
        conditions: List[rest.FieldCondition] = [
            rest.FieldCondition(key="org_id", match=rest.MatchValue(value=org_id)),
            rest.FieldCondition(key="agent_id", match=rest.MatchValue(value=agent_id)),
        ]
        if not include_deleted:
            conditions.append(rest.FieldCondition(key="deleted", match=rest.MatchValue(value=False)))

        records: List[MemoryRecord] = []
        offset = None
        while len(records) < limit:
            points, offset = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=rest.Filter(must=conditions),
                offset=offset,
                limit=100,
                with_vectors=False,
                with_payload=True,
            )
            if not points:
                break
            for point in points:
                payload = MemoryPayload.model_validate(point.payload)
                text = payload.text or ""
                if needle in text.lower():
                    records.append(MemoryRecord(id=str(point.id), text=text, payload=payload))
                    if len(records) >= limit:
                        break
            if offset is None:
                break
        return records
