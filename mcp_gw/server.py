"""Model Context Protocol server exposing memory tools."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Sequence

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools.base import ToolAnnotations

import mcp.types as mcp_types

from pydantic import BaseModel, Field

from core import MemoryCore, load_settings
from core.exceptions import NotFoundError
from core.models import DEFAULT_TTL_DAYS, MemoryAddRequest, MemoryScope, SearchRequest, UpdateMemoryRequest

from .schemas import (
    AddMemoriesResponse,
    CapabilitiesResource,
    DeleteMemoryResponse,
    BulkDeleteResponse,
    MemoryHitProtocol,
    MemoryHitView,
    MemoryItemView,
    MemoryRecordProtocol,
    ListMemoriesResponse,
    SearchMemoryResponse,
    UpdateMemoryResponse,
)

_settings = load_settings()
_core: Optional[MemoryCore] = None


def _get_core() -> MemoryCore:
    if _core is None:
        raise ToolError("memory core is not initialized")
    return _core


def _to_add_response(records: Sequence[MemoryRecordProtocol]) -> AddMemoriesResponse:
    return AddMemoriesResponse(items=[MemoryItemView.from_record(record) for record in records])


def _to_search_response(hits: Sequence[MemoryHitProtocol]) -> SearchMemoryResponse:
    return SearchMemoryResponse(hits=[MemoryHitView.from_hit(hit) for hit in hits])


def _to_update_response(record: MemoryRecordProtocol) -> UpdateMemoryResponse:
    return UpdateMemoryResponse(record=MemoryItemView.from_record(record))


def _to_list_response(records: Sequence[MemoryRecordProtocol]) -> ListMemoriesResponse:
    return ListMemoriesResponse(items=[MemoryItemView.from_record(record) for record in records])


@asynccontextmanager
async def _lifespan(app: FastMCP):  # type: ignore[type-arg]
    global _core
    core = MemoryCore(_settings)
    _core = core
    await core.startup()
    try:
        yield
    finally:
        try:
            await core.shutdown()
        finally:
            _core = None


app = FastMCP(
    "memscend-memory",
    instructions=(
        "Memscend provides multi-tenant memory tools. "
        "Every call must include org_id and agent_id (and user_id when writing). "
        "Clients that support elicitation will be prompted once per session. "
        "Others must provide these parameters directly."
    ),
    host="0.0.0.0",
    port=8050,
    lifespan=_lifespan,
)


SESSION_KEY = "memscend_identity_cache"


class TenantIdentity(BaseModel):
    org_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)


class OrgIdentity(BaseModel):
    org_id: str = Field(min_length=1)


class AgentIdentity(BaseModel):
    agent_id: str = Field(min_length=1)


class UserIdentity(BaseModel):
    user_id: str = Field(min_length=1)


def _identity_cache(ctx: Context) -> Dict[str, str]:
    session = ctx.request_context.session
    cache = getattr(session, SESSION_KEY, None)
    if cache is None or not isinstance(cache, dict):
        cache = {}
        setattr(session, SESSION_KEY, cache)
    return cache


def _client_supports_elicitation(ctx: Context) -> bool:
    try:
        session = ctx.request_context.session
    except ValueError:
        return False
    capability = mcp_types.ClientCapabilities(elicitation=mcp_types.ElicitationCapability())
    try:
        return session.check_client_capability(capability)
    except AttributeError:
        return False


async def _resolve_tenant(
    ctx: Context,
    org_id: Optional[str],
    agent_id: Optional[str],
) -> tuple[str, str]:
    cache = _identity_cache(ctx)

    if org_id:
        cache["org_id"] = org_id
    else:
        org_id = cache.get("org_id")

    if agent_id:
        cache["agent_id"] = agent_id
    else:
        agent_id = cache.get("agent_id")

    missing_org = not org_id
    missing_agent = not agent_id

    if not (missing_org or missing_agent):
        assert org_id is not None and agent_id is not None
        return org_id, agent_id

    if not _client_supports_elicitation(ctx):
        raise ToolError(
            "Missing org_id/agent_id. Provide them in the tool call or configure the MCP client "
            "to supply the tenancy headers."
        )

    if missing_org and missing_agent:
        result = await ctx.elicit(
            "Provide the Memscend organisation and agent identifiers.",
            TenantIdentity,
        )
        if result.action != "accept" or result.data is None:
            raise ToolError("org_id and agent_id are required")
        org_id = result.data.org_id
        agent_id = result.data.agent_id
    elif missing_org:
        result = await ctx.elicit("Provide the Memscend organisation identifier.", OrgIdentity)
        if result.action != "accept" or result.data is None:
            raise ToolError("org_id is required")
        org_id = result.data.org_id
    else:
        result = await ctx.elicit("Provide the Memscend agent identifier.", AgentIdentity)
        if result.action != "accept" or result.data is None:
            raise ToolError("agent_id is required")
        agent_id = result.data.agent_id

    cache["org_id"] = org_id
    cache["agent_id"] = agent_id
    return org_id, agent_id


async def _resolve_user(ctx: Context, user_id: Optional[str]) -> str:
    cache = _identity_cache(ctx)

    if user_id:
        cache["user_id"] = user_id
        return user_id

    cached = cache.get("user_id")
    if cached:
        return cached

    if not _client_supports_elicitation(ctx):
        raise ToolError(
            "Missing user_id. Provide it in the tool call or configure the client to prompt for it."
        )

    result = await ctx.elicit("Provide the user identifier for this memory.", UserIdentity)
    if result.action != "accept" or result.data is None:
        raise ToolError("user_id is required")
    cache["user_id"] = result.data.user_id
    return result.data.user_id


@app.tool(
    title="Add Memories",
    description="Persist user memories for downstream retrieval and reasoning.",
    structured_output=True,
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
    ),
)
async def add_memories(
    text: Optional[str],
    user_id: Optional[str],
    org_id: Optional[str],
    agent_id: Optional[str],
    ctx: Context,
    scope: str = MemoryScope.FACTS.value,
    tags: Optional[List[str]] = None,
    ttl_days: int = DEFAULT_TTL_DAYS,
    messages: Optional[List[Dict[str, Any]]] = None,
    source: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> AddMemoriesResponse:
    org_id, agent_id = await _resolve_tenant(ctx, org_id, agent_id)
    user_id = await _resolve_user(ctx, user_id)
    ctx.debug("add_memories invoked", org_id=org_id, agent_id=agent_id, user_id=user_id)
    request = MemoryAddRequest(
        text=text,
        messages=messages,
        user_id=user_id,
        scope=scope,
        tags=tags or [],
        ttl_days=ttl_days,
        source=source,
        idempotency_key=idempotency_key,
    )
    ctx.report_progress(0, 3, "queued")
    items = await _get_core().add(org_id, agent_id, request)
    ctx.report_progress(2, 3, message=f"persisted {len(items)} records")
    if not items:
        ctx.warning("No memories persisted after filtering/dedupe", org_id=org_id, agent_id=agent_id)
    ctx.report_progress(3, 3, "done")
    return _to_add_response(items)


@app.tool(
    title="Search Memory",
    description="Retrieve the most relevant memories for the supplied query.",
    structured_output=True,
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    ),
)
async def search_memory(
    query: str,
    org_id: Optional[str],
    agent_id: Optional[str],
    ctx: Context,
    user_id: Optional[str] = None,
    k: int = 6,
    scope: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> SearchMemoryResponse:
    org_id, agent_id = await _resolve_tenant(ctx, org_id, agent_id)
    ctx.debug("search_memory invoked", org_id=org_id, agent_id=agent_id, query=query)
    search_request = SearchRequest(
        query=query,
        user_id=user_id,
        k=k,
        scope=scope,
        tags=tags or [],
    )
    ctx.report_progress(0.0, 1.0, "embedding query")
    hits = await _get_core().search(org_id, agent_id, search_request)
    ctx.report_progress(1.0, 1.0, message=f"retrieved {len(hits)} hits")
    if not hits:
        ctx.info("No results for query", org_id=org_id, agent_id=agent_id)
    return _to_search_response(hits)


@app.tool(
    title="Update Memory",
    description="Patch text, scope, tags, TTL, or soft-delete flag for a memory.",
    structured_output=True,
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
    ),
)
async def update_memory(
    memory_id: str,
    org_id: Optional[str],
    agent_id: Optional[str],
    ctx: Context,
    text: Optional[str] = None,
    tags: Optional[List[str]] = None,
    scope: Optional[str] = None,
    ttl_days: Optional[int] = None,
    deleted: Optional[bool] = None,
) -> UpdateMemoryResponse:
    org_id, agent_id = await _resolve_tenant(ctx, org_id, agent_id)
    ctx.debug("update_memory invoked", memory_id=memory_id, org_id=org_id, agent_id=agent_id)
    update_request = UpdateMemoryRequest(
        text=text,
        tags=tags,
        scope=scope,
        ttl_days=ttl_days,
        deleted=deleted,
    )
    try:
        record = await _get_core().update(org_id, agent_id, memory_id, update_request)
    except NotFoundError as exc:  # pragma: no cover - defensive (integration tested)
        ctx.error("Memory not found during update", memory_id=memory_id, org_id=org_id, agent_id=agent_id)
        raise ToolError("memory not found for supplied identifiers") from exc
    return _to_update_response(record)


@app.tool(
    title="Delete Memory",
    description="Soft delete a memory, or hard delete when requested.",
    structured_output=True,
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
    ),
)
async def delete_memory(
    memory_id: str,
    org_id: Optional[str],
    agent_id: Optional[str],
    ctx: Context,
    hard: bool = False,
) -> DeleteMemoryResponse:
    org_id, agent_id = await _resolve_tenant(ctx, org_id, agent_id)
    ctx.debug("delete_memory invoked", memory_id=memory_id, org_id=org_id, agent_id=agent_id, hard=hard)
    try:
        await _get_core().delete(org_id, agent_id, memory_id, hard=hard)
    except NotFoundError as exc:
        ctx.warning(
            "Memory not found during delete",
            memory_id=memory_id,
            org_id=org_id,
            agent_id=agent_id,
            hard=hard,
        )
        raise ToolError("memory not found for supplied identifiers") from exc
    return DeleteMemoryResponse(ok=True)


@app.tool(
    title="List Memories",
    description="Return latest memories for this tenant (ordered by update time).",
    structured_output=True,
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False),
)
async def list_memories(
    ctx: Context,
    org_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 20,
    include_deleted: bool = False,
) -> ListMemoriesResponse:
    org_id, agent_id = await _resolve_tenant(ctx, org_id, agent_id)
    records = await _get_core().list(org_id, agent_id, limit=max(1, min(limit, 200)), include_deleted=include_deleted)
    return _to_list_response(records)


@app.tool(
    title="Open Memories",
    description="Fetch memories by their identifiers.",
    structured_output=True,
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False),
)
async def open_memories(
    ctx: Context,
    memory_ids: List[str],
    org_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> ListMemoriesResponse:
    if not memory_ids:
        return ListMemoriesResponse(items=[])
    org_id, agent_id = await _resolve_tenant(ctx, org_id, agent_id)
    records = await _get_core().get_many(org_id, agent_id, memory_ids)
    return _to_list_response(records)


@app.tool(
    title="Delete Memories",
    description="Delete multiple memories at once (soft by default).",
    structured_output=True,
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=True),
)
async def delete_memories(
    ctx: Context,
    memory_ids: List[str],
    org_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    hard: bool = False,
) -> BulkDeleteResponse:
    if not memory_ids:
        return BulkDeleteResponse(ok=True, ids=[], hard=hard)
    org_id, agent_id = await _resolve_tenant(ctx, org_id, agent_id)
    await _get_core().delete_many(org_id, agent_id, memory_ids, hard=hard)
    return BulkDeleteResponse(ok=True, ids=memory_ids, hard=hard)


@app.tool(
    title="Search Memory Text",
    description="Run a substring search against stored memories (non-semantic).",
    structured_output=True,
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False),
)
async def search_memory_text(
    ctx: Context,
    query: str,
    org_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 20,
    include_deleted: bool = False,
) -> ListMemoriesResponse:
    org_id, agent_id = await _resolve_tenant(ctx, org_id, agent_id)
    records = await _get_core().search_text(
        org_id,
        agent_id,
        query,
        limit=max(1, min(limit, 200)),
        include_deleted=include_deleted,
    )
    return _to_list_response(records)


@app.resource(
    "memscend://capabilities",
    title="Memscend Capabilities",
    description="Static defaults and capabilities for the Memscend MCP server.",
    mime_type="application/json",
)
async def capabilities() -> CapabilitiesResource:
    core_cfg = _settings.core
    return CapabilitiesResource(
        name="memscend-memory",
        version="2025-09-19",
        transports=["sse", "streamable-http", "stdio"],
        enabled_scopes=core_cfg.write.enabled_scopes,
        default_top_k=core_cfg.retrieval.top_k,
        vector_size=core_cfg.collection.vector_size,
        normalize_with_llm=core_cfg.write.normalize_with_llm,
    )


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    raw_transport = os.getenv("MCP_TRANSPORT", "sse").strip().lower()
    if raw_transport in {"stdio"}:
        transport = "stdio"
    elif raw_transport in {"streamable-http", "streamable_http", "http"}:
        transport = "streamable-http"
    else:
        transport = "sse"
    app.run(transport=transport)
