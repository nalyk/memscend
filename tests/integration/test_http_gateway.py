from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from core.config.models import CoreConfig, ExternalServiceConfig, SecurityConfig, Settings
from core.models import MemoryHit, MemoryPayload, MemoryRecord


class DummyCore:
    def __init__(self, record: MemoryRecord, hit: MemoryHit) -> None:
        self.record = record
        self.hit = hit
        self.startup = AsyncMock()
        self.shutdown = AsyncMock()
        self.add = AsyncMock(return_value=[record])
        self.search = AsyncMock(return_value=[hit])
        self.update = AsyncMock(return_value=record)
        self.delete = AsyncMock(return_value=None)


@pytest.fixture
def client():
    from http_gw.app import app

    payload = MemoryPayload(
        org_id="org-1",
        agent_id="agent-1",
        user_id="user-7",
        scope="prefs",
        tags=["quiet"],
        text="No notifications after 22:00",
    )
    record = MemoryRecord(id="abc", text=payload.text, payload=payload)
    hit = MemoryHit(id="abc", score=0.9, text=payload.text, payload=payload)

    dummy_core = DummyCore(record, hit)

    settings = Settings(
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

    with patch("http_gw.app.load_settings", return_value=settings), patch(
        "http_gw.app.MemoryCore", return_value=dummy_core
    ):
        with TestClient(app) as test_client:
            yield test_client, dummy_core


def test_add_search_update_delete_flow(client):
    test_client, dummy_core = client
    headers = {"X-Org-Id": "org-1", "X-Agent-Id": "agent-1"}

    add_payload = {
        "user_id": "user-7",
        "text": "No notifications after 22:00",
        "scope": "prefs",
    }
    response = test_client.post("/api/v1/mem/add", json=add_payload, headers=headers)
    assert response.status_code == 201
    assert response.json()["items"][0]["id"] == "abc"
    dummy_core.add.assert_awaited()

    response = test_client.get("/api/v1/mem/search", params={"q": "notifications"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["hits"][0]["id"] == "abc"
    dummy_core.search.assert_awaited()

    patch_payload = {"text": "No notifications after 21:00"}
    response = test_client.patch("/api/v1/mem/abc", json=patch_payload, headers=headers)
    assert response.status_code == 200
    dummy_core.update.assert_awaited()

    response = test_client.delete("/api/v1/mem/abc", headers=headers)
    assert response.status_code == 200
    dummy_core.delete.assert_awaited()

