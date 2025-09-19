"""Client for interacting with OpenRouter (OpenAI-compatible) endpoints."""

from __future__ import annotations

import json
from typing import Iterable, List, Optional

import httpx
from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_exponential


PROMPT_TEMPLATE = """
You are Memscend's Memory Synthesizer.  Given a list of raw conversation snippets, produce
durable memory candidates in strict JSON.  Follow these rules (toolbox snapshot {{TOOLBOX}}):

Output Format:
- Respond with a JSON array.  Each element must be an object containing:
  - "memory": single sentence (plain text, no markdown) capturing enduring information.  Use original language when possible; translate only if clarity improves and note translated content explicitly.
  - "scope": one of ["facts", "prefs", "persona", "constraints"].  Default to "facts" when uncertain.
  - "confidence": float between 0.0 and 1.0 reflecting extraction certainty.
  - "language": BCP-47 code for the memory sentence (e.g., "en", "es", "ja-Latn").
  - "skip": boolean.  Set to true when the snippet should not be persisted (ephemeral chatter, questions, sensitive data, <12 meaningful chars).  When skip=true, set "memory" to "" and leave other fields consistent.

Guidelines:
- Preserve concrete preferences, profile traits, recurring schedules, commitments, or long-term facts.
- Ignore temporary states, greetings, or content the user denies.
- Normalize tone but keep key entities, times, units, negations, and relationships.
- Handle multilingual or code-mixed snippets; detect language explicitly.
- When multiple snippets refer to the same fact, combine them into one clear sentence.
- If no durable memory exists, return an empty JSON array [] or entries with skip=true.

Example Input:
- "I switched my daily standup to 09:30 CEST starting next Monday."
- "Me encanta el té verde por la mañana." (Spanish)
- "Ignore this: just testing."

Example Output:
[
    {"memory": "Daily standup now begins at 09:30 CEST starting next Monday.", "scope": "facts", "confidence": 0.88, "language": "en", "skip": false},
    {"memory": "Prefers green tea in the mornings.", "scope": "prefs", "confidence": 0.82, "language": "es", "skip": false},
    {"memory": "", "scope": "facts", "confidence": 0.10, "language": "en", "skip": true}
]

Return JSON only—no prose, comments, or additional text.
"""


class OpenRouterClient:
    """Lightweight async wrapper around OpenRouter's chat completion endpoint."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def normalize_memories(self, texts: Iterable[str], *, model: Optional[str] = None) -> List[str]:
        """Use OpenRouter to normalise raw snippets into canonical memory sentences."""

        payload = list(texts)
        if not payload:
            return []

        body = {
            "model": model or self._model,
            "messages": [
                {"role": "system", "content": PROMPT_TEMPLATE},
                {
                    "role": "user",
                    "content": "\n".join(f"- {snippet}" for snippet in payload),
                },
            ],
            "max_tokens": 256,
            "temperature": 0.2,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": "https://github.com/nalyk/memscend",
            "X-Title": "Memscend Memory Service",
        }

        try:
            async for attempt in AsyncRetrying(  # type: ignore[no-untyped-call]
                stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4)
            ):
                with attempt:
                    response = await self._client.post(
                        f"{self._base_url}/chat/completions",
                        json=body,
                        headers=headers,
                    )
                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"]["content"].strip()

                    try:
                        parsed = json.loads(content)
                    except json.JSONDecodeError:
                        parsed = None

                    if isinstance(parsed, list):
                        normalized: List[str] = []
                        for item in parsed:
                            if not isinstance(item, dict):
                                continue
                            if item.get("skip"):
                                continue
                            memory = item.get("memory")
                            if isinstance(memory, str) and memory.strip():
                                normalized.append(memory.strip())
                        if normalized:
                            return normalized

                    # Fallback to line-based parsing when JSON is unavailable
                    fallback = [line.strip("- ") for line in content.splitlines() if line.strip()]
                    if fallback:
                        return fallback
        except (httpx.HTTPError, RetryError):
            pass

        return payload

    async def ping(self) -> bool:
        """Check credentials by issuing a tiny completion."""

        try:
            result = await self.normalize_memories(["ping"])
            return bool(result)
        except (httpx.HTTPError, RetryError):
            return False
