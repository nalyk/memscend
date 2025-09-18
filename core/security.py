"""Authentication and tenancy enforcement helpers."""

from __future__ import annotations

import asyncio
from typing import Dict, Optional, Tuple

import jwt
import httpx
from jwt import InvalidTokenError

from .config.models import SecurityConfig
from .exceptions import AuthenticationError, AuthorizationError


class SecurityService:
    """Validates bearer tokens and enforces tenancy headers."""

    def __init__(self, config: SecurityConfig) -> None:
        self._config = config
        # Interpret shared_secrets as mapping org_id -> token string
        self._token_map = {token: org_id for org_id, token in config.shared_secrets.items()}
        self._jwks_cache: Optional[Dict[str, str]] = None
        self._lock = asyncio.Lock()

    async def _fetch_jwks(self) -> Dict[str, str]:
        if not self._config.jwk_url:
            return {}
        async with self._lock:
            if self._jwks_cache is not None:
                return self._jwks_cache
            async with httpx.AsyncClient() as client:
                response = await client.get(str(self._config.jwk_url))
                response.raise_for_status()
                body = response.json()
                keys = {item["kid"]: item for item in body.get("keys", [])}
                self._jwks_cache = keys
                return keys

    async def authenticate(self, authorization: Optional[str]) -> Optional[str]:
        if not authorization:
            if self._token_map:
                raise AuthenticationError("missing bearer token")
            return None

        prefix = "Bearer "
        if not authorization.startswith(prefix):
            raise AuthenticationError("authorization header must use Bearer scheme")
        token = authorization[len(prefix) :].strip()

        if token in self._token_map:
            return self._token_map[token]

        if self._config.jwk_url:
            jwks = await self._fetch_jwks()
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            key = jwks.get(kid)
            if not key:
                raise AuthenticationError("unknown signing key")
            try:
                payload = jwt.decode(
                    token,
                    key=jwt.algorithms.RSAAlgorithm.from_jwk(key),
                    audience=self._config.jwt_audience,
                    issuer=self._config.jwt_issuer,
                    algorithms=[key["alg"]],
                )
            except InvalidTokenError as exc:  # pragma: no cover - delegated to PyJWT
                raise AuthenticationError("invalid JWT") from exc
            return str(payload.get("org_id"))

        raise AuthenticationError("unauthorized token")

    def validate_tenancy(self, derived_org_id: Optional[str], header_org_id: Optional[str], header_agent_id: Optional[str]) -> Tuple[str, str]:
        if self._config.enforce_headers:
            if not header_org_id:
                raise AuthorizationError("X-Org-Id header is required")
            if not header_agent_id:
                raise AuthorizationError("X-Agent-Id header is required")
        org_id = header_org_id or derived_org_id
        if not org_id:
            raise AuthorizationError("organisation identifier is missing")
        if derived_org_id and header_org_id and derived_org_id != header_org_id:
            raise AuthorizationError("token org does not match header org")
        agent_id = header_agent_id or "default"
        return org_id, agent_id

