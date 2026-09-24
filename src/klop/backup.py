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
        base = f"{ts_ms:015d}-{digest}"
        # Guarantee a free slot: if this exact id already exists (e.g. two
        # backups of the same path within the same millisecond), append an
        # incrementing numeric suffix until we find an unused slot name.
        # This preserves the timestamp prefix (so ids still sort oldest
        # first) while never reusing/overwriting an existing backup slot.
        candidate = base
        suffix = 0
        while (self.root / candidate).exists():
            suffix += 1
            candidate = f"{base}-{suffix:02d}"
        return candidate

    def backup(self, path: Path) -> str:
        path = Path(path)
        backup_id = self._new_id(path)
        slot = self.root / backup_id
        slot.mkdir(parents=True)
        shutil.copy2(path, slot / path.name)
        meta = {
            "original_path": str(path),
            "filename": path.name,
            "created": time.time(),
        }
        (slot / "meta.json").write_text(json.dumps(meta))
        return backup_id

    def record_conversion(self, backup_id: str, dest: Path, size: int) -> None:
        """Note that this backup's original was converted into `dest`.

        Lets `restore` clean up the file the convert created. Size is stored so
        restore can tell our own output apart from a file the user has since
        changed.
        """
        meta_file = self.root / backup_id / "meta.json"
        if not meta_file.exists():
            raise KeyError(backup_id)
        meta = json.loads(meta_file.read_text())
        meta["converted_path"] = str(dest)
        meta["converted_size"] = int(size)
        meta_file.write_text(json.dumps(meta))

    def restore(self, backup_id: str) -> Path:
        slot = self.root / backup_id
        meta_file = slot / "meta.json"
        if not meta_file.exists():
            raise KeyError(backup_id)
        meta = json.loads(meta_file.read_text())
        original = Path(meta["original_path"])
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(slot / meta["filename"], original)
        self._remove_converted(meta)
        return original

    @staticmethod
    def _remove_converted(meta: dict) -> None:
        """Delete the file a convert produced, if it is still exactly ours.

        Absent for same-extension optimizations and for backups written before
        conversions were tracked. We only unlink when the size still matches
        what we wrote: if the user edited or replaced that file, it is their
        work and we leave it alone.
        """
        converted = meta.get("converted_path")
        if not converted:
            return
        path = Path(converted)
        try:
            if path.stat().st_size != meta.get("converted_size"):
                return
            path.unlink()
        except OSError:
            pass  # already gone, or not ours to remove — never fail the undo

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
