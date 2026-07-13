from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path


class BackupStore:
    """Stores copies of originals so optimizations can be undone."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _new_id(self, original: Path) -> str:
        ts_ms = int(time.time() * 1000)
        digest = hashlib.sha1(str(original).encode()).hexdigest()[:8]
        return f"{ts_ms:015d}-{digest}"

    def backup(self, path: Path) -> str:
        path = Path(path)
        backup_id = self._new_id(path)
        slot = self.root / backup_id
        slot.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, slot / path.name)
        meta = {
            "original_path": str(path),
            "filename": path.name,
            "created": time.time(),
        }
        (slot / "meta.json").write_text(json.dumps(meta))
        return backup_id

    def restore(self, backup_id: str) -> Path:
        slot = self.root / backup_id
        meta_file = slot / "meta.json"
        if not meta_file.exists():
            raise KeyError(backup_id)
        meta = json.loads(meta_file.read_text())
        original = Path(meta["original_path"])
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(slot / meta["filename"], original)
        return original

    def _slots(self) -> list[tuple[str, float, int]]:
        """Return (backup_id, created_ts, size_bytes) per slot, oldest first."""
        out = []
        for slot in self.root.iterdir():
            meta_file = slot / "meta.json"
            if not slot.is_dir() or not meta_file.exists():
                continue
            meta = json.loads(meta_file.read_text())
            size = sum(f.stat().st_size for f in slot.iterdir() if f.is_file())
            out.append((slot.name, float(meta["created"]), size))
        out.sort(key=lambda t: t[1])
        return out

    def prune(self, max_age_days: int, max_bytes: int, now: float | None = None) -> int:
        if now is None:
            now = time.time()
        removed = 0
        slots = self._slots()

        # 1) Age-based removal.
        max_age_seconds = max_age_days * 86400
        survivors = []
        for backup_id, created, size in slots:
            if now - created > max_age_seconds:
                shutil.rmtree(self.root / backup_id)
                removed += 1
            else:
                survivors.append((backup_id, created, size))

        # 2) Size-based removal, dropping oldest until under budget.
        total = sum(size for _, _, size in survivors)
        for backup_id, _created, size in survivors:
            if total <= max_bytes:
                break
            shutil.rmtree(self.root / backup_id)
            total -= size
            removed += 1
        return removed
