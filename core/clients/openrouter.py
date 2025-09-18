"""Client for interacting with OpenRouter (OpenAI-compatible) endpoints."""

from __future__ import annotations

from typing import Iterable, List, Optional

import httpx
from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_exponential


PROMPT_TEMPLATE = (
    "You act as a memory extraction assistant. Given conversation notes, return a concise "
    "sentence capturing lasting information or preference. Respond with one bullet per input, "
    "plain text, no markdown."
)


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

        headers = {"Authorization": f"Bearer {self._api_key}"}

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
                return [line.strip("- ") for line in content.splitlines() if line.strip()]

        return payload

    async def ping(self) -> bool:
        """Check credentials by issuing a tiny completion."""

        try:
            result = await self.normalize_memories(["ping"])
            return bool(result)
        except (httpx.HTTPError, RetryError):
            return False
