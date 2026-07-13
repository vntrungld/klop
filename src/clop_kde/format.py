from __future__ import annotations


def human_size(n: float) -> str:
    """Format a byte count as a short human-readable string (e.g. '2.0KB')."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.0f}B"


def percent_saved(original: int, new: int) -> int:
    """Integer percentage reduction from original to new size (0 if original <= 0)."""
    if original <= 0:
        return 0
    return round((original - new) / original * 100)
