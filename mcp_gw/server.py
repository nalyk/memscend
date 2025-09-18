"""Model Context Protocol server exposing memory tools."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from core import MemoryCore, load_settings
from core.models import MemoryAddRequest, SearchRequest, UpdateMemoryRequest
from core.exceptions import NotFoundError

_settings = load_settings()
_core = MemoryCore(_settings)


@asynccontextmanager
async def _lifespan(app: FastMCP):  # type: ignore[type-arg]
    await _core.startup()
    try:
        yield
    finally:
        await _core.shutdown()


app = FastMCP("memory", host="0.0.0.0", port=8050, lifespan=_lifespan)


@app.tool()
async def add_memories(
    text: Optional[str],
    user_id: str,
    org_id: str,
    agent_id: str,
    scope: str = "facts",
    tags: Optional[List[str]] = None,
    ttl_days: int = 365,
) -> Dict[str, Any]:
    request = MemoryAddRequest(
        text=text,
        user_id=user_id,
        scope=scope,
        tags=tags or [],
        ttl_days=ttl_days,
    )
    items = await _core.add(org_id, agent_id, request)
    return {
        "items": [
            {
                "id": item.id,
                "text": item.text,
                "payload": item.payload.model_dump(mode="json"),
            }
            for item in items
        ]
    }


@app.tool()
async def search_memory(
    query: str,
    org_id: str,
    agent_id: str,
    user_id: Optional[str] = None,
    k: int = 6,
    scope: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    search_request = SearchRequest(
        query=query,
        user_id=user_id,
        k=k,
        scope=scope,
        tags=tags or [],
    )
    hits = await _core.search(org_id, agent_id, search_request)
    return {
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


@app.tool()
async def update_memory(
    memory_id: str,
    org_id: str,
    agent_id: str,
    text: Optional[str] = None,
    tags: Optional[List[str]] = None,
    scope: Optional[str] = None,
    ttl_days: Optional[int] = None,
    deleted: Optional[bool] = None,
) -> Dict[str, Any]:
    update_request = UpdateMemoryRequest(
        text=text,
        tags=tags,
        scope=scope,
        ttl_days=ttl_days,
        deleted=deleted,
    )
    record = await _core.update(org_id, agent_id, memory_id, update_request)
    return {
        "id": record.id,
        "text": record.text,
        "payload": record.payload.model_dump(mode="json"),
    }


@app.tool()
async def delete_memory(
    memory_id: str,
    org_id: str,
    agent_id: str,
    hard: bool = False,
) -> Dict[str, Any]:
    try:
        await _core.delete(org_id, agent_id, memory_id, hard=hard)
    except NotFoundError:
        return {"ok": False, "reason": "not_found"}
    return {"ok": True}


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    app.run()
