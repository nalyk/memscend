"""FastAPI gateway exposing the memory service over HTTP."""

from __future__ import annotations

from typing import AsyncGenerator, List, Optional

import orjson
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field

from core import MemoryCore, load_settings
from core.exceptions import AuthenticationError, AuthorizationError, MemoryServiceError, NotFoundError
from core.models import MemoryAddRequest, SearchRequest, UpdateMemoryRequest
from core.security import SecurityService

app = FastAPI(title="Memory Service Gateway", version="0.1.0")


@app.on_event("startup")
async def startup_event() -> None:
    settings = load_settings()
    memory_core = MemoryCore(settings)
    await memory_core.startup()
    app.state.settings = settings
    app.state.core = memory_core
    app.state.security = SecurityService(settings.security)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    core: MemoryCore | None = getattr(app.state, "core", None)
    if core:
        await core.shutdown()


def get_app_core(request: Request) -> MemoryCore:
    core: MemoryCore | None = getattr(request.app.state, "core", None)
    if not core:
        raise HTTPException(status_code=503, detail="service unavailable")
    return core


def get_security(request: Request) -> SecurityService:
    security: SecurityService | None = getattr(request.app.state, "security", None)
    if not security:
        raise HTTPException(status_code=503, detail="security unavailable")
    return security


async def tenancy_context(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    org_id: Optional[str] = Header(default=None, alias="X-Org-Id"),
    agent_id: Optional[str] = Header(default=None, alias="X-Agent-Id"),
) -> tuple[str, str]:
    security = get_security(request)
    try:
        derived_org = await security.authenticate(authorization)
        resolved_org, resolved_agent = security.validate_tenancy(derived_org, org_id, agent_id)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return resolved_org, resolved_agent


@app.exception_handler(MemoryServiceError)
async def memory_error_handler(_: Request, exc: MemoryServiceError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.post("/api/v1/mem/add")
async def add_memories(
    request: MemoryAddRequest,
    tenant: tuple[str, str] = Depends(tenancy_context),
    core: MemoryCore = Depends(get_app_core),
) -> JSONResponse:
    org_id, agent_id = tenant
    items = await core.add(org_id, agent_id, request)
    response = {
        "items": [
            {
                "id": item.id,
                "text": item.text,
                "payload": item.payload.model_dump(mode="json"),
            }
            for item in items
        ]
    }
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)


@app.get("/api/v1/mem/search")
async def search_memories(
    request: Request,
    q: str = Query(..., alias="q"),
    user_id: Optional[str] = Query(default=None),
    k: int = Query(default=6, ge=1, le=50),
    scope: Optional[str] = Query(default=None),
    tags: List[str] = Query(default_factory=list),
    tenant: tuple[str, str] = Depends(tenancy_context),
    core: MemoryCore = Depends(get_app_core),
) -> JSONResponse:
    org_id, agent_id = tenant
    search_request = SearchRequest(query=q, user_id=user_id, k=k, scope=scope, tags=tags)
    hits = await core.search(org_id, agent_id, search_request)
    response = {
        "hits": [
            {
                "id": hit.id,
                "score": hit.score,
                "text": hit.text,
                "payload": hit.payload.model_dump(mode="json"),
            }
            for hit in hits
        ]
    }
    return JSONResponse(content=response)


async def _search_generator(
    core: MemoryCore,
    org_id: str,
    agent_id: str,
    search_request: SearchRequest,
) -> AsyncGenerator[dict, None]:
    hits = await core.search(org_id, agent_id, search_request)
    for hit in hits:
        yield {
            "type": "hit",
            "id": hit.id,
            "score": hit.score,
            "text": hit.text,
            "payload": hit.payload.model_dump(mode="json"),
        }
    yield {"type": "done"}


@app.get("/api/v1/mem/search/ndjson")
async def search_memories_ndjson(
    q: str = Query(..., alias="q"),
    user_id: Optional[str] = Query(default=None),
    k: int = Query(default=6, ge=1, le=50),
    scope: Optional[str] = Query(default=None),
    tags: List[str] = Query(default_factory=list),
    tenant: tuple[str, str] = Depends(tenancy_context),
    core: MemoryCore = Depends(get_app_core),
) -> StreamingResponse:
    org_id, agent_id = tenant
    search_request = SearchRequest(query=q, user_id=user_id, k=k, scope=scope, tags=tags)

    async def ndjson_stream() -> AsyncGenerator[bytes, None]:
        async for event in _search_generator(core, org_id, agent_id, search_request):
            serialised = {
                **event,
                "payload": event.get("payload"),
            }
            yield orjson.dumps(serialised) + b"\n"

    return StreamingResponse(ndjson_stream(), media_type="application/x-ndjson")


@app.get("/api/v1/mem/search/stream")
async def search_memories_stream(
    q: str = Query(..., alias="q"),
    user_id: Optional[str] = Query(default=None),
    k: int = Query(default=6, ge=1, le=50),
    scope: Optional[str] = Query(default=None),
    tags: List[str] = Query(default_factory=list),
    tenant: tuple[str, str] = Depends(tenancy_context),
    core: MemoryCore = Depends(get_app_core),
) -> EventSourceResponse:
    org_id, agent_id = tenant
    search_request = SearchRequest(query=q, user_id=user_id, k=k, scope=scope, tags=tags)

    async def event_stream() -> AsyncGenerator[dict, None]:
        async for event in _search_generator(core, org_id, agent_id, search_request):
            yield {"event": event["type"], "data": orjson.dumps(event).decode("utf-8")}

    return EventSourceResponse(event_stream(), ping=20.0)


@app.patch("/api/v1/mem/{memory_id}")
async def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
    tenant: tuple[str, str] = Depends(tenancy_context),
    core: MemoryCore = Depends(get_app_core),
) -> JSONResponse:
    org_id, agent_id = tenant
    try:
        record = await core.update(org_id, agent_id, memory_id, request)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(
        content={
            "id": record.id,
            "text": record.text,
            "payload": record.payload.model_dump(mode="json"),
        }
    )


@app.delete("/api/v1/mem/{memory_id}")
async def delete_memory(
    memory_id: str,
    hard: bool = Query(default=False),
    tenant: tuple[str, str] = Depends(tenancy_context),
    core: MemoryCore = Depends(get_app_core),
) -> JSONResponse:
    org_id, agent_id = tenant
    try:
        await core.delete(org_id, agent_id, memory_id, hard=hard)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(content={"ok": True})


class IdsPayload(BaseModel):
    ids: List[str] = Field(default_factory=list, min_items=1)


class BatchDeletePayload(BaseModel):
    ids: List[str] = Field(default_factory=list, min_items=1)
    hard: bool = False


def _record_to_dict(record) -> dict:
    return {
        "id": record.id,
        "text": record.text,
        "payload": record.payload.model_dump(mode="json"),
    }


@app.get("/api/v1/mem/list")
async def list_memories(
    limit: int = Query(default=20, ge=1, le=200),
    include_deleted: bool = Query(default=False),
    tenant: tuple[str, str] = Depends(tenancy_context),
    core: MemoryCore = Depends(get_app_core),
) -> JSONResponse:
    org_id, agent_id = tenant
    records = await core.list(org_id, agent_id, limit=limit, include_deleted=include_deleted)
    return JSONResponse(content={"items": [_record_to_dict(record) for record in records]})


@app.post("/api/v1/mem/open")
async def open_memories(
    payload: IdsPayload,
    tenant: tuple[str, str] = Depends(tenancy_context),
    core: MemoryCore = Depends(get_app_core),
) -> JSONResponse:
    org_id, agent_id = tenant
    records = await core.get_many(org_id, agent_id, payload.ids)
    return JSONResponse(content={"items": [_record_to_dict(record) for record in records]})


@app.post("/api/v1/mem/delete/batch")
async def delete_memories_batch(
    payload: BatchDeletePayload,
    tenant: tuple[str, str] = Depends(tenancy_context),
    core: MemoryCore = Depends(get_app_core),
) -> JSONResponse:
    org_id, agent_id = tenant
    await core.delete_many(org_id, agent_id, payload.ids, hard=payload.hard)
    return JSONResponse(content={"ok": True, "ids": payload.ids, "hard": payload.hard})


@app.get("/api/v1/mem/search/text")
async def search_memories_text(
    q: str = Query(..., alias="q"),
    limit: int = Query(default=20, ge=1, le=200),
    include_deleted: bool = Query(default=False),
    tenant: tuple[str, str] = Depends(tenancy_context),
    core: MemoryCore = Depends(get_app_core),
) -> JSONResponse:
    org_id, agent_id = tenant
    records = await core.search_text(org_id, agent_id, q, limit=limit, include_deleted=include_deleted)
    return JSONResponse(content={"items": [_record_to_dict(record) for record in records]})
