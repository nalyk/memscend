"""Pydantic models describing runtime configuration."""

from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field, HttpUrl, PositiveInt, validator


DEFAULT_SCOPES = ["prefs", "facts", "persona", "constraints"]


class WritePolicy(BaseModel):
    """Rules that govern whether and how a memory is persisted."""

    enabled_scopes: list[str] = Field(default_factory=lambda: DEFAULT_SCOPES.copy())
    min_chars: PositiveInt = 12
    deduplicate: bool = True
    normalize_with_llm: bool = True
    max_batch: PositiveInt = 32


class RetrievalPolicy(BaseModel):
    """Parameters for semantic search in Qdrant."""

    top_k: PositiveInt = 6
    ef_search: PositiveInt = 64
    include_text: bool = True


class CollectionPolicy(BaseModel):
    """Vector collection tuning."""

    name: str = "memories"
    vector_size: PositiveInt = 768
    distance: str = "Cosine"
    on_disk_payload: bool = True


class TenantOverrides(BaseModel):
    """Per-tenant overrides for policies and collections."""

    write: Optional[WritePolicy] = None
    retrieval: Optional[RetrievalPolicy] = None
    collection: Optional[CollectionPolicy] = None
    model: Optional[str] = None
    embedding_dims: Optional[PositiveInt] = None


class AgentOverrides(TenantOverrides):
    """Agent-level overrides inherits tenant fields."""

    pass


class OrgConfig(TenantOverrides):
    """Organisation-level configuration containing optional agent overrides."""

    agents: Dict[str, AgentOverrides] = Field(default_factory=dict)


class CoreConfig(BaseModel):
    """Top-level configuration tree for runtime resolution."""

    write: WritePolicy = Field(default_factory=WritePolicy)
    retrieval: RetrievalPolicy = Field(default_factory=RetrievalPolicy)
    collection: CollectionPolicy = Field(default_factory=CollectionPolicy)
    model: str = "openrouter/auto"
    embedding_dims: PositiveInt = 768
    organisations: Dict[str, OrgConfig] = Field(default_factory=dict)

    @validator("embedding_dims")
    def validate_dims(cls, value: int) -> int:  # noqa: D417
        if value not in (128, 256, 512, 768):
            raise ValueError("embedding dimensions must be one of 128, 256, 512, 768")
        return value


class SecurityConfig(BaseModel):
    """Authentication and tenancy enforcement settings."""

    jwt_audience: str = "memory-service"
    jwt_issuer: str = "memory-service"
    jwk_url: Optional[HttpUrl] = None
    shared_secrets: Dict[str, str] = Field(default_factory=dict)
    enforce_headers: bool = True


class ExternalServiceConfig(BaseModel):
    """External backend endpoints and API credentials."""

    openrouter_api_key: str = Field(..., repr=False)
    openrouter_base_url: HttpUrl = HttpUrl("https://openrouter.ai/api/v1")
    tei_base_url: HttpUrl = HttpUrl("http://localhost:3000")
    qdrant_url: HttpUrl = HttpUrl("http://localhost:6333")
    qdrant_api_key: Optional[str] = Field(default=None, repr=False)
    qdrant_collection: str = "memories"


class Settings(BaseModel):
    """Full configuration for the core application."""

    environment: str = Field(default="development")
    core: CoreConfig = Field(default_factory=CoreConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    services: ExternalServiceConfig

