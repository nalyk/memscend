"""Entry point for running background checks on the memory core."""

from __future__ import annotations

import asyncio
import signal

from rich.console import Console

from . import MemoryCore, load_settings

console = Console()


async def _serve_forever(stop_event: asyncio.Event) -> None:
    await stop_event.wait()


async def main() -> None:
    settings = load_settings()
    memory_core = MemoryCore(settings)

    stop_event = asyncio.Event()

    def _handle_stop(*_: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_stop)

    await memory_core.startup()
    console.log("Memory core initialised")

    try:
        await _serve_forever(stop_event)
    finally:
        await memory_core.shutdown()
        console.log("Memory core shut down")


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    asyncio.run(main())
