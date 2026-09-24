from __future__ import annotations

import shutil
from collections.abc import Iterable

KNOWN_TOOLS: tuple[str, ...] = (
    "pngquant",
    "jpegoptim",
    "oxipng",
    "gifsicle",
    "cwebp",
    "vips",
    "ffmpeg",
    "gs",
)


def detect_capabilities(tools: Iterable[str] = KNOWN_TOOLS) -> dict[str, str | None]:
    """Map each tool name to its resolved executable path, or None if absent."""
    return {name: shutil.which(name) for name in tools}


def has_tool(caps: dict[str, str | None], name: str) -> bool:
    return caps.get(name) is not None
