"""Helpers for loading application configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import ValidationError

from .models import Settings

CONFIG_ENV_VAR = "MEMORY_CONFIG_FILE"
DEFAULT_CONFIG_PATH = Path("config/memory-config.yaml")


def _load_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _maybe_set(target: Dict[str, Any], key: str, value: Any) -> None:
    if value is not None and key not in target:
        target[key] = value


def _inject_env_overrides(raw: Dict[str, Any]) -> Dict[str, Any]:
    services = raw.setdefault("services", {})
    _maybe_set(services, "openrouter_api_key", os.getenv("OPENROUTER_API_KEY"))
    _maybe_set(services, "qdrant_api_key", os.getenv("QDRANT_API_KEY"))
    _maybe_set(services, "tei_base_url", os.getenv("TEI_BASE_URL"))
    _maybe_set(services, "openrouter_base_url", os.getenv("OPENROUTER_BASE_URL"))
    _maybe_set(services, "qdrant_url", os.getenv("QDRANT_URL"))

    security = raw.setdefault("security", {})
    shared_secret = os.getenv("MEMORY_SHARED_SECRET")
    if shared_secret:
        security.setdefault("shared_secrets", {"default": shared_secret})

    env = os.getenv("MEMORY_ENVIRONMENT")
    if env:
        raw["environment"] = env

    return raw


def load_settings(config_path: str | os.PathLike[str] | None = None) -> Settings:
    """Load settings from YAML and environment variables."""

    chosen_path = Path(config_path) if config_path else Path(os.getenv(CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH))
    raw_config = _load_file(chosen_path)
    hydrated = _inject_env_overrides(raw_config)

    try:
        return Settings(**hydrated)
    except ValidationError as exc:  # pragma: no cover - delegated to callers
        raise RuntimeError(f"Invalid configuration: {exc}") from exc


SettingsType = Settings

