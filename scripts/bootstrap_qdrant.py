"""Create Qdrant collections using the configured memory core."""

from __future__ import annotations

import asyncio

from core import MemoryCore, load_settings


async def main() -> None:
    settings = load_settings()
    core = MemoryCore(settings)
    await core.startup()
    await core.shutdown()


if __name__ == "__main__":  # pragma: no cover - manual utility
    asyncio.run(main())

