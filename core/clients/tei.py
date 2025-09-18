"""TEI embedding client."""

from __future__ import annotations

from typing import Iterable, List

import httpx
from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_fixed


class TEIClient:
    """Async HTTP client for Hugging Face Text Embeddings Inference."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=3.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def embed(self, texts: Iterable[str]) -> List[List[float]]:
        payload = list(texts)
        if not payload:
            return []

        request = {"input": payload}

        async for attempt in AsyncRetrying(  # type: ignore[no-untyped-call]
            stop=stop_after_attempt(3), wait=wait_fixed(0.4)
        ):
            with attempt:
                response = await self._client.post(
                    f"{self._base_url}/v1/embeddings",
                    json=request,
                )
                response.raise_for_status()
                data = response.json()
                return [item["embedding"] for item in data["data"]]

        raise RuntimeError("TEI embedding retries exhausted")

    async def ping(self) -> bool:
        try:
            vectors = await self.embed(["ping"])
            return bool(vectors and vectors[0])
        except (httpx.HTTPError, RetryError):
            return False

