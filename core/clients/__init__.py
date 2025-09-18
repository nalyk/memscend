"""External service clients used by the memory core."""

from .openrouter import OpenRouterClient
from .tei import TEIClient

__all__ = ["OpenRouterClient", "TEIClient"]
