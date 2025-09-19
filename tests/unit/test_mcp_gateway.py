"""Unit tests for MCP gateway helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcp.server.fastmcp.exceptions import ToolError

from core.models import MemoryHit, MemoryPayload, MemoryRecord

from mcp_gw import server


def _make_payload(**overrides: object) -> MemoryPayload:
    base = {
        "org_id": "acme",
        "agent_id": "assistant",
        "user_id": "user-1",
        "scope": "facts",
        "tags": ["unit"],
        "ttl_days": 30,
        "text": overrides.get("text", "hello world"),
    }
    base.update(overrides)
    return MemoryPayload(**base)


def test_to_add_response_serializes_payload() -> None:
    payload = _make_payload()
    record = MemoryRecord(id="mem-1", text="hello world", payload=payload)

    response = server._to_add_response([record])  # type: ignore[attr-defined]

    assert response.items[0].id == "mem-1"
    assert response.items[0].payload.org_id == payload.org_id
    assert response.items[0].payload.text == payload.text


def test_to_search_response_preserves_scores() -> None:
    payload = _make_payload(text="memory hit")
    hit = MemoryHit(id="hit-1", text="memory hit", score=0.87, payload=payload)

    response = server._to_search_response([hit])  # type: ignore[attr-defined]

    assert pytest.approx(response.hits[0].score, rel=1e-6) == 0.87
    assert response.hits[0].payload.tags == payload.tags


@pytest.mark.asyncio
async def test_capabilities_resource_reflects_settings() -> None:
    resource = await server.capabilities()  # type: ignore[attr-defined]

    assert resource.vector_size == server._settings.core.collection.vector_size
    assert "sse" in resource.transports


class _DummySession:
    def __init__(self, supports_elicitation: bool) -> None:
        self.supports_elicitation = supports_elicitation

    def check_client_capability(self, capability) -> bool:  # pragma: no cover - trivial
        return self.supports_elicitation


class _DummyRequestContext:
    def __init__(self, session: _DummySession) -> None:
        self.session = session


class _DummyContext:
    def __init__(self, session: _DummySession, elicitation_queue: list[SimpleNamespace]) -> None:
        self._session = session
        self._request_context = _DummyRequestContext(session)
        self._elicitation_queue = elicitation_queue

    @property
    def request_context(self):  # pragma: no cover - simple accessor
        return self._request_context

    @property
    def session(self):  # pragma: no cover - simple accessor
        return self._session

    async def elicit(self, message, schema):  # pragma: no cover - simple dequeue
        if not self._elicitation_queue:
            return SimpleNamespace(action="decline", data=None)
        return self._elicitation_queue.pop(0)

    async def debug(self, *_, **__):  # pragma: no cover - not needed in tests
        return None


@pytest.mark.asyncio
async def test_resolve_tenant_requires_elicitation_support() -> None:
    ctx = _DummyContext(_DummySession(False), [])
    with pytest.raises(ToolError):
        await server._resolve_tenant(ctx, None, None)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_resolve_tenant_uses_elicitation_and_caches() -> None:
    elicited = SimpleNamespace(
        action="accept",
        data=server.TenantIdentity(org_id="org-1", agent_id="agent-1"),
    )
    ctx = _DummyContext(_DummySession(True), [elicited])

    org_id, agent_id = await server._resolve_tenant(ctx, None, None)  # type: ignore[attr-defined]
    assert (org_id, agent_id) == ("org-1", "agent-1")

    # Cache should avoid a second elicitation even without queue entries
    org_id, agent_id = await server._resolve_tenant(ctx, None, None)  # type: ignore[attr-defined]
    assert (org_id, agent_id) == ("org-1", "agent-1")


@pytest.mark.asyncio
async def test_resolve_user_caches_value() -> None:
    ctx = _DummyContext(_DummySession(False), [])
    user = await server._resolve_user(ctx, "user-42")  # type: ignore[attr-defined]
    assert user == "user-42"

    user = await server._resolve_user(ctx, None)  # type: ignore[attr-defined]
    assert user == "user-42"
