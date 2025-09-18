"""Utility helpers for memory service."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime


def make_id(org_id: str, agent_id: str, text: str) -> str:
    """Deterministic UUID5 based on tenant and memory text."""

    namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"memory::{org_id}::{agent_id}")
    return str(uuid.uuid5(namespace, text))


def compute_hash(org_id: str, agent_id: str, user_id: str, text: str) -> str:
    """Stable SHA-256 digest used for deduplication."""

    digest = hashlib.sha256()
    digest.update(org_id.encode("utf-8"))
    digest.update(b"|")
    digest.update(agent_id.encode("utf-8"))
    digest.update(b"|")
    digest.update(user_id.encode("utf-8"))
    digest.update(b"|")
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def apply_time_decay(score: float, created_at: datetime, now: datetime, half_life_days: int = 90) -> float:
    """Apply exponential time decay to relevance scores."""

    days = max((now - created_at).days, 0)
    decay_factor = 0.5 ** (days / half_life_days)
    return score * decay_factor

