from __future__ import annotations

from pathlib import Path


def dedup(path: Path) -> Path:
    """Return `path` if free, else the first available '{stem}-{i}{suffix}'."""
    if not path.exists():
        return path
    i = 1
    while True:
        cand = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1
