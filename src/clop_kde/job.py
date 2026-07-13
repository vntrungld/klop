from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path

from .media import MediaType


class JobStatus(enum.Enum):
    OPTIMIZED = "optimized"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class OptimizationJob:
    source_path: Path
    media_type: MediaType | None = None
    options: dict = field(default_factory=dict)


@dataclass
class JobResult:
    status: JobStatus
    path: Path
    original_size: int
    new_size: int
    backup_id: str | None = None
    message: str = ""

    @property
    def saved_bytes(self) -> int:
        return max(0, self.original_size - self.new_size)
