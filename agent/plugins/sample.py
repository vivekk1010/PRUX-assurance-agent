"""Side-effect-free example handler for import-path tool configuration."""

from typing import Any


def normalize_text(arguments: dict[str, Any]) -> dict[str, str]:
    """Collapse repeated whitespace in the supplied text."""
    return {"text": " ".join(arguments["text"].split())}
