"""Write and search policy helpers."""

from __future__ import annotations

from .config.models import WritePolicy


class WritePolicyEngine:
    """Evaluates whether a piece of text should become a memory."""

    def __init__(self, policy: WritePolicy) -> None:
        self._policy = policy

    def should_persist(self, text: str, scope: str) -> bool:
        if not text or len(text.strip()) < self._policy.min_chars:
            return False
        if scope not in self._policy.enabled_scopes:
            return False
        return True

    @property
    def deduplicate(self) -> bool:
        return self._policy.deduplicate

    @property
    def normalize_with_llm(self) -> bool:
        return self._policy.normalize_with_llm

    @property
    def max_batch(self) -> int:
        return self._policy.max_batch

