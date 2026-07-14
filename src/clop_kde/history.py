from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path

_MAX = 200


def _default_history_file() -> Path:
    override = os.environ.get("CLOP_KDE_HISTORY_FILE")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "clop-kde" / "history.jsonl"


@dataclass(frozen=True)
class HistoryEntry:
    id: str
    kind: str  # "file" | "clipboard"
    name: str
    path: str | None
    original_size: int
    new_size: int
    backup_id: str | None
    timestamp: float
    undone: bool = False

    @property
    def saved_bytes(self) -> int:
        return max(0, self.original_size - self.new_size)

    @property
    def undoable(self) -> bool:
        return self.backup_id is not None and not self.undone

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "original_size": self.original_size,
            "new_size": self.new_size,
            "backup_id": self.backup_id,
            "timestamp": self.timestamp,
            "undone": self.undone,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HistoryEntry":
        return cls(
            id=d["id"],
            kind=d["kind"],
            name=d["name"],
            path=d.get("path"),
            original_size=d["original_size"],
            new_size=d["new_size"],
            backup_id=d.get("backup_id"),
            timestamp=d["timestamp"],
            undone=d.get("undone", False),
        )


class HistoryStore:
    """Append-only JSONL history of optimizations, capped at _MAX entries.
    Qt-free so the CLI can use it. Reads tolerate a torn trailing line."""

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path is not None else _default_history_file()
        self._counter = 0

    def record(
        self, kind, name, path, original_size, new_size, backup_id=None
    ) -> HistoryEntry:
        ts = time.time()
        self._counter += 1
        entry = HistoryEntry(
            id=f"{int(ts * 1e9)}-{self._counter}",
            kind=kind,
            name=name,
            path=path,
            original_size=original_size,
            new_size=new_size,
            backup_id=backup_id,
            timestamp=ts,
            undone=False,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict()) + "\n")
        self._prune()
        return entry

    def entries(self) -> list[HistoryEntry]:
        return list(reversed(self._read_all()))

    def mark_undone(self, backup_id: str) -> bool:
        if not self._path.exists():
            return False
        rows = self._read_all()
        changed = False
        for i, e in enumerate(rows):
            if e.backup_id == backup_id and not e.undone:
                rows[i] = replace(e, undone=True)
                changed = True
        if changed:
            self._rewrite(rows)
        return changed

    def _read_all(self) -> list[HistoryEntry]:
        if not self._path.exists():
            return []
        out: list[HistoryEntry] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(HistoryEntry.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError):
                    continue  # skip a torn/corrupt line, don't fail the read
        return out

    def _prune(self) -> None:
        rows = self._read_all()
        if len(rows) > _MAX:
            self._rewrite(rows[-_MAX:])

    def _rewrite(self, rows: list[HistoryEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for e in rows:
                fh.write(json.dumps(e.to_dict()) + "\n")
        os.replace(tmp, self._path)  # atomic swap
