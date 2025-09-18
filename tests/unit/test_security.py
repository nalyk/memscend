import pytest

from core.config.models import SecurityConfig
from core.security import SecurityService
from core.exceptions import AuthenticationError, AuthorizationError


@pytest.mark.asyncio
async def test_authenticate_with_shared_secret():
    config = SecurityConfig(shared_secrets={"org-123": "secret-token"})
    service = SecurityService(config)

    org_id = await service.authenticate("Bearer secret-token")
    assert org_id == "org-123"


@pytest.mark.asyncio
async def test_authenticate_rejects_missing_token():
    config = SecurityConfig(shared_secrets={"org-123": "secret-token"})
    service = SecurityService(config)

    with pytest.raises(AuthenticationError):
        await service.authenticate(None)


@pytest.mark.asyncio
async def test_validate_tenancy_checks_headers():
    config = SecurityConfig(enforce_headers=True)
    service = SecurityService(config)

    with pytest.raises(AuthorizationError):
        service.validate_tenancy(None, header_org_id=None, header_agent_id=None)

    org_id, agent_id = service.validate_tenancy("org-123", header_org_id="org-123", header_agent_id="agent-9")
    assert org_id == "org-123"
    assert agent_id == "agent-9"

