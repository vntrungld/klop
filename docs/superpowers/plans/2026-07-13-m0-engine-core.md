# Klop M0 — Skeleton + Engine Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the headless optimization engine for Klop — config, capability detection, backup/undo, a PNG+JPEG optimizer registry, the Engine that ties them together, and a `klop` CLI that exercises the whole thing with no UI.

**Architecture:** Pure-Python package (`klop`) with focused modules: media detection, config, capability detection, backup store, optimizer registry, engine, CLI. The engine takes an `OptimizationJob`, backs up the original, runs an external optimizer via `subprocess`, and replaces the original only if the result is meaningfully smaller. No Qt / PySide6 in M0 — it is added in M1 when the daemon gains an event loop.

**Tech Stack:** Python 3.11+ (stdlib `tomllib`, `subprocess`, `shutil`), pytest, Pillow (dev-only, to synthesize test images). External optimizer CLIs `pngquant` and `jpegoptim` (optional, detected at runtime).

## Global Constraints

- **Python 3.11+** required (uses stdlib `tomllib`).
- **No PySide6 / Qt in M0** — pure Python only. PySide6 arrives in M1.
- **In-place replacement + backup/undo** is the write model — never write `*-optimized` copies.
- **Only replace the original if the result is smaller** by at least `min_bytes_saved` (default 1 byte, configurable); otherwise keep the original and report `unchanged`.
- **pngquant is the default PNG optimizer** (lossy); `oxipng` lossless is a later option (not in M0).
- **All optimizers are optional** — detected at startup; a media type with no available tool is `skipped` cleanly, never an error.
- **Config path:** `~/.config/klop/config.toml` (missing file → all defaults).
- **Backups path:** `~/.local/share/klop/backups/<backup_id>/`.
- **Commit message format** (from the user's global rules): first line `{Action}: {short description}` where Action ∈ {Update, Fix, WIP, Hotfix}, imperative, <72 chars; blank line; body; then `Co-Authored-By: Claude <noreply@anthropic.com>`.

---

## File Structure

```
klop/
├── pyproject.toml                 # hatchling build, console script, deps
├── src/klop/
│   ├── __init__.py                # version
│   ├── media.py                   # MediaType enum + detect_media_type()
│   ├── config.py                  # Config dataclass + load_config()
│   ├── capabilities.py            # detect_capabilities()
│   ├── backup.py                  # BackupStore (backup/restore/prune)
│   ├── job.py                     # OptimizationJob + JobResult dataclasses
│   ├── optimizers.py              # Optimizer registry (pngquant, jpegoptim), select_optimizer()
│   ├── engine.py                  # Engine.optimize() / Engine.undo()
│   └── cli.py                     # argparse entrypoint: optimize / undo / caps
└── tests/
    ├── conftest.py                # fixtures: sample_png, sample_jpeg, tmp config/backup roots
    ├── test_media.py
    ├── test_config.py
    ├── test_capabilities.py
    ├── test_backup.py
    ├── test_optimizers.py
    ├── test_engine.py
    └── test_cli.py
```

Each module has one responsibility and a narrow interface, so tasks are independently reviewable.

---

## Task 1: Project scaffold + media type detection

**Files:**
- Create: `pyproject.toml`
- Create: `src/klop/__init__.py`
- Create: `src/klop/media.py`
- Test: `tests/test_media.py`
- Test: `tests/conftest.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `klop.media.MediaType` — `Enum` with members `PNG, JPEG, GIF, WEBP, HEIC, VIDEO, PDF, UNKNOWN`.
  - `klop.media.detect_media_type(path: pathlib.Path) -> MediaType` — magic-bytes first, extension fallback.
  - conftest fixtures `sample_png(tmp_path) -> Path` and `sample_jpeg(tmp_path) -> Path` (real image files via Pillow).

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "klop"
version = "0.0.1"
description = "Background media optimizer for KDE Plasma 6"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8", "Pillow>=10"]

[project.scripts]
klop = "klop.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/klop"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `src/klop/__init__.py`**

```python
__version__ = "0.0.1"
```

- [ ] **Step 3: Create the dev environment and install**

Run:
```bash
python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
```
Expected: installs klop (editable), pytest, Pillow with no errors. Use `.venv/bin/pytest` and `.venv/bin/klop` for all later steps.

- [ ] **Step 4: Write `tests/conftest.py` with image fixtures**

```python
import pytest
from PIL import Image


@pytest.fixture
def sample_png(tmp_path):
    p = tmp_path / "sample.png"
    # Noisy gradient so optimizers have something real to compress.
    img = Image.new("RGBA", (256, 256))
    px = img.load()
    for y in range(256):
        for x in range(256):
            px[x, y] = (x, y, (x * y) % 256, 255)
    img.save(p, "PNG")
    return p


@pytest.fixture
def sample_jpeg(tmp_path):
    p = tmp_path / "sample.jpg"
    img = Image.new("RGB", (256, 256))
    px = img.load()
    for y in range(256):
        for x in range(256):
            px[x, y] = (x, y, (x + y) % 256)
    img.save(p, "JPEG", quality=95)
    return p
```

- [ ] **Step 5: Write the failing test `tests/test_media.py`**

```python
from pathlib import Path

from klop.media import MediaType, detect_media_type


def test_detect_png_by_magic(sample_png):
    assert detect_media_type(sample_png) == MediaType.PNG


def test_detect_jpeg_by_magic(sample_jpeg):
    assert detect_media_type(sample_jpeg) == MediaType.JPEG


def test_magic_bytes_beat_wrong_extension(sample_png, tmp_path):
    lying = tmp_path / "actually_png.jpg"
    lying.write_bytes(sample_png.read_bytes())
    assert detect_media_type(lying) == MediaType.PNG


def test_pdf_by_magic(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.7\n...")
    assert detect_media_type(p) == MediaType.PDF


def test_unknown_for_text(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_bytes(b"hello world")
    assert detect_media_type(p) == MediaType.UNKNOWN
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_media.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.media'`.

- [ ] **Step 7: Write `src/klop/media.py`**

```python
from __future__ import annotations

import enum
from pathlib import Path


class MediaType(enum.Enum):
    PNG = "png"
    JPEG = "jpeg"
    GIF = "gif"
    WEBP = "webp"
    HEIC = "heic"
    VIDEO = "video"
    PDF = "pdf"
    UNKNOWN = "unknown"


_EXT_MAP = {
    ".png": MediaType.PNG,
    ".jpg": MediaType.JPEG,
    ".jpeg": MediaType.JPEG,
    ".gif": MediaType.GIF,
    ".webp": MediaType.WEBP,
    ".heic": MediaType.HEIC,
    ".heif": MediaType.HEIC,
    ".pdf": MediaType.PDF,
    ".mp4": MediaType.VIDEO,
    ".mov": MediaType.VIDEO,
    ".mkv": MediaType.VIDEO,
    ".webm": MediaType.VIDEO,
}


def _detect_by_magic(header: bytes) -> MediaType | None:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaType.PNG
    if header.startswith(b"\xff\xd8\xff"):
        return MediaType.JPEG
    if header.startswith((b"GIF87a", b"GIF89a")):
        return MediaType.GIF
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return MediaType.WEBP
    if header.startswith(b"%PDF"):
        return MediaType.PDF
    # ISO-BMFF: "....ftyp<brand>"; HEIC brands start with hei/hev/mif.
    if header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand[:3] in (b"hei", b"hev", b"mif"):
            return MediaType.HEIC
        return MediaType.VIDEO
    if header.startswith(b"\x1a\x45\xdf\xa3"):  # Matroska / WebM (EBML)
        return MediaType.VIDEO
    return None


def detect_media_type(path: Path) -> MediaType:
    """Identify media type by magic bytes, falling back to file extension."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(32)
    except OSError:
        header = b""
    by_magic = _detect_by_magic(header)
    if by_magic is not None:
        return by_magic
    return _EXT_MAP.get(path.suffix.lower(), MediaType.UNKNOWN)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_media.py -v`
Expected: PASS (5 passed).

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/klop/__init__.py src/klop/media.py tests/conftest.py tests/test_media.py
git commit -m "Update: add package scaffold and media type detection

Add the hatchling-based project scaffold with a console-script
entrypoint, plus media.py providing MediaType and a magic-bytes-first
detect_media_type(). Tests cover PNG/JPEG/PDF detection and the
extension-lying case.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Config loader

**Files:**
- Create: `src/klop/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from other modules.
- Produces:
  - `klop.config.Config` — frozen dataclass with fields:
    `png_lossy: bool = True`, `pngquant_quality: tuple[int, int] = (65, 80)`,
    `jpeg_max_quality: int = 80`, `min_bytes_saved: int = 1`, `concurrency: int = 2`,
    `backup_retention_days: int = 7`, `backup_max_bytes: int = 500 * 1024 * 1024`.
  - `klop.config.default_config_path() -> Path` → `~/.config/klop/config.toml`.
  - `klop.config.load_config(path: Path | None = None) -> Config` — missing file → defaults; partial file → defaults for absent keys.

- [ ] **Step 1: Write the failing test `tests/test_config.py`**

```python
from klop.config import Config, load_config


def test_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg == Config()
    assert cfg.png_lossy is True
    assert cfg.pngquant_quality == (65, 80)
    assert cfg.min_bytes_saved == 1


def test_partial_file_fills_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        "png_lossy = false\n"
        "jpeg_max_quality = 60\n"
        "pngquant_quality = [40, 70]\n"
    )
    cfg = load_config(p)
    assert cfg.png_lossy is False
    assert cfg.jpeg_max_quality == 60
    assert cfg.pngquant_quality == (40, 70)
    # Untouched keys keep defaults.
    assert cfg.concurrency == 2
    assert cfg.backup_retention_days == 7


def test_unknown_keys_are_ignored(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("bogus_key = 123\njpeg_max_quality = 50\n")
    cfg = load_config(p)
    assert cfg.jpeg_max_quality == 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.config'`.

- [ ] **Step 3: Write `src/klop/config.py`**

```python
from __future__ import annotations

import dataclasses
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    png_lossy: bool = True
    pngquant_quality: tuple[int, int] = (65, 80)
    jpeg_max_quality: int = 80
    min_bytes_saved: int = 1
    concurrency: int = 2
    backup_retention_days: int = 7
    backup_max_bytes: int = 500 * 1024 * 1024


def default_config_path() -> Path:
    return Path.home() / ".config" / "klop" / "config.toml"


_FIELD_NAMES = {f.name for f in dataclasses.fields(Config)}


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML; missing file or absent keys fall back to defaults."""
    if path is None:
        path = default_config_path()
    try:
        raw = tomllib.loads(Path(path).read_text())
    except (FileNotFoundError, OSError):
        return Config()

    kwargs = {}
    for key, value in raw.items():
        if key not in _FIELD_NAMES:
            continue
        if key == "pngquant_quality" and isinstance(value, list):
            value = tuple(value)
        kwargs[key] = value
    return Config(**kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/klop/config.py tests/test_config.py
git commit -m "Update: add TOML config loader with defaults

Add Config (frozen dataclass) and load_config(), which reads
~/.config/klop/config.toml, falls back to defaults when the file
is missing, fills defaults for absent keys, and ignores unknown keys.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Capability detection

**Files:**
- Create: `src/klop/capabilities.py`
- Test: `tests/test_capabilities.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `klop.capabilities.KNOWN_TOOLS: tuple[str, ...]` — tool names M0+ cares about (`"pngquant", "jpegoptim", "oxipng", "gifsicle", "cwebp", "vips", "ffmpeg", "gs"`).
  - `klop.capabilities.detect_capabilities(tools=KNOWN_TOOLS) -> dict[str, str | None]` — maps tool name → absolute path (via `shutil.which`) or `None`.
  - `klop.capabilities.has_tool(caps: dict[str, str | None], name: str) -> bool`.

- [ ] **Step 1: Write the failing test `tests/test_capabilities.py`**

```python
import shutil

from klop.capabilities import KNOWN_TOOLS, detect_capabilities, has_tool


def test_detects_present_tool(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    caps = detect_capabilities(["pngquant", "jpegoptim"])
    assert caps == {"pngquant": "/usr/bin/pngquant", "jpegoptim": "/usr/bin/jpegoptim"}
    assert has_tool(caps, "pngquant") is True


def test_detects_absent_tool(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    caps = detect_capabilities(["pngquant"])
    assert caps == {"pngquant": None}
    assert has_tool(caps, "pngquant") is False


def test_default_scans_known_tools(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    caps = detect_capabilities()
    assert set(caps) == set(KNOWN_TOOLS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_capabilities.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.capabilities'`.

- [ ] **Step 3: Write `src/klop/capabilities.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_capabilities.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/klop/capabilities.py tests/test_capabilities.py
git commit -m "Update: add optimizer capability detection

Add detect_capabilities(), which resolves each known optimizer CLI to
its path via shutil.which so the engine can degrade gracefully when a
tool is missing. Tests stub PATH to cover present and absent tools.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: BackupStore (backup / restore / prune)

**Files:**
- Create: `src/klop/backup.py`
- Test: `tests/test_backup.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `klop.backup.BackupStore(root: Path)`.
  - `.backup(path: Path) -> str` — copies the file into `root/<backup_id>/`, writes a `meta.json` recording the absolute original path and timestamp; returns `backup_id`.
  - `.restore(backup_id: str) -> Path` — copies the backed-up file back to its original path; returns that path. Raises `KeyError` if the id is unknown.
  - `.prune(max_age_days: int, max_bytes: int, now: float | None = None) -> int` — deletes oldest backups over the age or total-size budget; returns count removed.
  - `backup_id` format: `"<unix_ts_ms>-<8 hex of sha1(original path)>"` (sortable oldest-first, collision-resistant per path).

- [ ] **Step 1: Write the failing test `tests/test_backup.py`**

```python
import json
from pathlib import Path

import pytest

from klop.backup import BackupStore


def test_backup_then_restore_roundtrip(tmp_path):
    original = tmp_path / "photo.png"
    original.write_bytes(b"ORIGINAL-BYTES")
    store = BackupStore(tmp_path / "backups")

    backup_id = store.backup(original)
    # Simulate the optimizer overwriting the original.
    original.write_bytes(b"OPTIMIZED-SMALLER")

    restored = store.restore(backup_id)
    assert restored == original
    assert original.read_bytes() == b"ORIGINAL-BYTES"


def test_backup_writes_meta(tmp_path):
    original = tmp_path / "photo.png"
    original.write_bytes(b"X")
    store = BackupStore(tmp_path / "backups")
    backup_id = store.backup(original)

    meta = json.loads((tmp_path / "backups" / backup_id / "meta.json").read_text())
    assert meta["original_path"] == str(original)


def test_restore_unknown_id_raises(tmp_path):
    store = BackupStore(tmp_path / "backups")
    with pytest.raises(KeyError):
        store.restore("does-not-exist")


def test_prune_by_age(tmp_path):
    original = tmp_path / "a.png"
    original.write_bytes(b"data")
    store = BackupStore(tmp_path / "backups")
    bid = store.backup(original)

    # now is far in the future so the backup is older than max_age_days.
    future = 10**12  # seconds; way past the 1970-based backup timestamp
    removed = store.prune(max_age_days=1, max_bytes=10**9, now=future)
    assert removed == 1
    assert not (tmp_path / "backups" / bid).exists()


def test_prune_by_size_keeps_newest(tmp_path):
    store = BackupStore(tmp_path / "backups")
    ids = []
    for i in range(3):
        f = tmp_path / f"f{i}.bin"
        f.write_bytes(b"Z" * 1000)
        ids.append(store.backup(f))

    # Budget fits only one ~1000-byte backup; oldest two removed.
    removed = store.prune(max_age_days=9999, max_bytes=1500, now=None)
    assert removed == 2
    assert (tmp_path / "backups" / ids[-1]).exists()
    assert not (tmp_path / "backups" / ids[0]).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_backup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.backup'`.

- [ ] **Step 3: Write `src/klop/backup.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_backup.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/klop/backup.py tests/test_backup.py
git commit -m "Update: add BackupStore for undo support

Add BackupStore with backup/restore roundtrip (copying originals into
timestamped slots with meta.json) and prune() enforcing age and total
-size budgets, dropping oldest first. Backs the engine's undo path.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Optimizer registry (pngquant + jpegoptim)

**Files:**
- Create: `src/klop/optimizers.py`
- Test: `tests/test_optimizers.py`

**Interfaces:**
- Consumes: `klop.media.MediaType`, `klop.config.Config`, `klop.capabilities` (dict form).
- Produces:
  - `klop.optimizers.Optimizer` — dataclass: `name: str`, `tool: str`, `build_command(inp: Path, out: Path, cfg: Config) -> list[str]`, `use_stdout: bool`.
  - `klop.optimizers.PNGQUANT: Optimizer` and `klop.optimizers.JPEGOPTIM: Optimizer`.
  - `klop.optimizers.select_optimizer(media_type, caps, cfg) -> Optimizer | None` — returns the first optimizer for that media type whose `tool` is available, else `None`.

Notes for the implementer:
- **pngquant** writes to an explicit output file: `pngquant --quality=<lo>-<hi> --force --skip-if-larger --strip --output <out> -- <in>`. `use_stdout=False`. With `--skip-if-larger` it may exit non-zero and not write `out`; the engine treats a missing/empty `out` as "no improvement".
- **jpegoptim** cannot target an arbitrary output filename, so we use its stdout mode: `jpegoptim --max=<q> --strip-all --stdout -- <in>`. `use_stdout=True`; the engine redirects stdout into `out`.

- [ ] **Step 1: Write the failing test `tests/test_optimizers.py`**

```python
from pathlib import Path

from klop.config import Config
from klop.media import MediaType
from klop.optimizers import (
    JPEGOPTIM,
    PNGQUANT,
    select_optimizer,
)


def test_pngquant_command_shape():
    cfg = Config(pngquant_quality=(40, 70))
    cmd = PNGQUANT.build_command(Path("/in.png"), Path("/out.png"), cfg)
    assert cmd[0] == "pngquant"
    assert "--quality=40-70" in cmd
    assert "--output" in cmd
    assert cmd[cmd.index("--output") + 1] == "/out.png"
    assert cmd[-1] == "/in.png"
    assert PNGQUANT.use_stdout is False


def test_jpegoptim_command_shape():
    cfg = Config(jpeg_max_quality=60)
    cmd = JPEGOPTIM.build_command(Path("/in.jpg"), Path("/out.jpg"), cfg)
    assert cmd[0] == "jpegoptim"
    assert "--max=60" in cmd
    assert "--stdout" in cmd
    assert cmd[-1] == "/in.jpg"
    assert JPEGOPTIM.use_stdout is True


def test_select_prefers_available_tool():
    caps = {"pngquant": "/usr/bin/pngquant", "jpegoptim": None}
    assert select_optimizer(MediaType.PNG, caps, Config()) is PNGQUANT
    assert select_optimizer(MediaType.JPEG, caps, Config()) is None


def test_select_unknown_media_returns_none():
    caps = {"pngquant": "/usr/bin/pngquant"}
    assert select_optimizer(MediaType.UNKNOWN, caps, Config()) is None
    assert select_optimizer(MediaType.PDF, caps, Config()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_optimizers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.optimizers'`.

- [ ] **Step 3: Write `src/klop/optimizers.py`**

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .media import MediaType


@dataclass(frozen=True)
class Optimizer:
    name: str
    tool: str
    _builder: Callable[[Path, Path, Config], list[str]]
    use_stdout: bool = False

    def build_command(self, inp: Path, out: Path, cfg: Config) -> list[str]:
        return self._builder(inp, out, cfg)


def _pngquant_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    lo, hi = cfg.pngquant_quality
    return [
        "pngquant",
        f"--quality={lo}-{hi}",
        "--force",
        "--skip-if-larger",
        "--strip",
        "--output",
        str(out),
        "--",
        str(inp),
    ]


def _jpegoptim_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    return [
        "jpegoptim",
        f"--max={cfg.jpeg_max_quality}",
        "--strip-all",
        "--stdout",
        "--",
        str(inp),
    ]


PNGQUANT = Optimizer("pngquant", "pngquant", _pngquant_cmd, use_stdout=False)
JPEGOPTIM = Optimizer("jpegoptim", "jpegoptim", _jpegoptim_cmd, use_stdout=True)

# First available optimizer per media type wins.
_REGISTRY: dict[MediaType, list[Optimizer]] = {
    MediaType.PNG: [PNGQUANT],
    MediaType.JPEG: [JPEGOPTIM],
}


def select_optimizer(
    media_type: MediaType, caps: dict[str, str | None], cfg: Config
) -> Optimizer | None:
    for opt in _REGISTRY.get(media_type, []):
        if caps.get(opt.tool) is not None:
            return opt
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_optimizers.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/klop/optimizers.py tests/test_optimizers.py
git commit -m "Update: add pngquant/jpegoptim optimizer registry

Add the Optimizer dataclass plus PNGQUANT and JPEGOPTIM command
builders and select_optimizer(), which picks the first available tool
for a media type. jpegoptim uses stdout mode since it cannot target an
arbitrary output path; pngquant writes to an explicit --output file.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Engine (optimize + undo)

**Files:**
- Create: `src/klop/job.py`
- Create: `src/klop/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `Config`, `BackupStore`, capabilities dict, `select_optimizer`, `detect_media_type`, `Optimizer`.
- Produces:
  - `klop.job.OptimizationJob` — dataclass: `source_path: Path`, `media_type: MediaType | None = None` (engine auto-detects when `None`), `options: dict = field(default_factory=dict)`.
  - `klop.job.JobStatus` — `Enum`: `OPTIMIZED, UNCHANGED, SKIPPED, ERROR`.
  - `klop.job.JobResult` — dataclass: `status: JobStatus`, `path: Path`, `original_size: int`, `new_size: int`, `backup_id: str | None`, `message: str = ""`. Property `saved_bytes -> int` = `max(0, original_size - new_size)`.
  - `klop.engine.Engine(config, backup_store, capabilities, runner=None)` where `runner(cmd: list[str], stdout_path: Path | None) -> int` defaults to a real subprocess runner; injectable for tests.
  - `.optimize(job: OptimizationJob) -> JobResult`.
  - `.undo(backup_id: str) -> Path`.

Engine algorithm for `optimize`:
1. Resolve `media_type` (auto-detect if `None`). Record `original_size`.
2. `select_optimizer`; if `None` → `JobResult(SKIPPED, ...)` with a message naming the missing tool.
3. Run the optimizer into a temp file in the same directory (via `runner`). If `use_stdout`, redirect stdout to the temp file; else the tool writes it.
4. If the temp file is missing/empty or `runner` returned non-zero → `UNCHANGED` (no replacement, no backup).
5. `new_size = temp.size`. If `original_size - new_size < config.min_bytes_saved` → `UNCHANGED`, delete temp.
6. Otherwise: `backup_id = backup_store.backup(source)`, atomically replace the original with the temp file (`os.replace`), return `OPTIMIZED`.

- [ ] **Step 1: Write the failing test `tests/test_engine.py`**

```python
import shutil
from pathlib import Path

import pytest

from klop.backup import BackupStore
from klop.config import Config
from klop.engine import Engine
from klop.job import JobResult, JobStatus, OptimizationJob
from klop.media import MediaType


def make_engine(tmp_path, caps, runner):
    return Engine(
        config=Config(),
        backup_store=BackupStore(tmp_path / "backups"),
        capabilities=caps,
        runner=runner,
    )


def test_skipped_when_no_optimizer(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    def runner(cmd, stdout_path):  # never called
        raise AssertionError("runner should not run when no tool available")

    engine = make_engine(tmp_path, {"pngquant": None}, runner)
    result = engine.optimize(OptimizationJob(source_path=f))
    assert result.status == JobStatus.SKIPPED
    assert f.read_bytes().startswith(b"\x89PNG")  # untouched


def test_optimized_replaces_and_backs_up(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000)

    def runner(cmd, stdout_path):
        # Simulate a tool writing a smaller file to the temp output.
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        return 0

    engine = make_engine(tmp_path, {"pngquant": "/usr/bin/pngquant"}, runner)
    result = engine.optimize(OptimizationJob(source_path=f))
    assert result.status == JobStatus.OPTIMIZED
    assert result.saved_bytes > 0
    assert len(f.read_bytes()) == 108  # replaced with smaller output
    assert result.backup_id is not None

    restored = engine.undo(result.backup_id)
    assert restored == f
    assert len(f.read_bytes()) == 1008  # original restored


def test_unchanged_when_not_smaller(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    def runner(cmd, stdout_path):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)  # same size
        return 0

    engine = make_engine(tmp_path, {"pngquant": "/usr/bin/pngquant"}, runner)
    result = engine.optimize(OptimizationJob(source_path=f))
    assert result.status == JobStatus.UNCHANGED
    assert result.backup_id is None


def test_unchanged_when_runner_fails(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    def runner(cmd, stdout_path):
        return 99  # pngquant "quality not met" style failure, no output written

    engine = make_engine(tmp_path, {"pngquant": "/usr/bin/pngquant"}, runner)
    result = engine.optimize(OptimizationJob(source_path=f))
    assert result.status == JobStatus.UNCHANGED
    assert result.backup_id is None


@pytest.mark.skipif(not shutil.which("pngquant"), reason="pngquant not installed")
def test_real_pngquant_end_to_end(tmp_path, sample_png):
    target = tmp_path / "real.png"
    target.write_bytes(sample_png.read_bytes())
    original_size = target.stat().st_size

    engine = Engine(
        config=Config(),
        backup_store=BackupStore(tmp_path / "backups"),
        capabilities={"pngquant": shutil.which("pngquant")},
    )
    result = engine.optimize(OptimizationJob(source_path=target))
    assert result.status in (JobStatus.OPTIMIZED, JobStatus.UNCHANGED)
    if result.status == JobStatus.OPTIMIZED:
        assert target.stat().st_size < original_size
        engine.undo(result.backup_id)
        assert target.stat().st_size == original_size
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.job'`.

- [ ] **Step 3: Write `src/klop/job.py`**

```python
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
```

- [ ] **Step 4: Write `src/klop/engine.py`**

```python
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .backup import BackupStore
from .config import Config
from .job import JobResult, JobStatus, OptimizationJob
from .media import detect_media_type
from .optimizers import select_optimizer


def _default_runner(cmd: list[str], stdout_path: Path | None) -> int:
    """Run cmd; if stdout_path is set, redirect stdout into it. Returns exit code."""
    if stdout_path is not None:
        with open(stdout_path, "wb") as out:
            proc = subprocess.run(cmd, stdout=out, stderr=subprocess.DEVNULL)
    else:
        proc = subprocess.run(cmd, stderr=subprocess.DEVNULL)
    return proc.returncode


class Engine:
    def __init__(self, config: Config, backup_store: BackupStore, capabilities, runner=None):
        self.config = config
        self.backup_store = backup_store
        self.capabilities = capabilities
        self._runner = runner or _default_runner

    def optimize(self, job: OptimizationJob) -> JobResult:
        source = Path(job.source_path)
        media_type = job.media_type or detect_media_type(source)
        original_size = source.stat().st_size

        optimizer = select_optimizer(media_type, self.capabilities, self.config)
        if optimizer is None:
            return JobResult(
                status=JobStatus.SKIPPED,
                path=source,
                original_size=original_size,
                new_size=original_size,
                message=f"no optimizer available for {media_type.value}",
            )

        fd, tmp_name = tempfile.mkstemp(dir=source.parent, suffix=source.suffix)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            cmd = optimizer.build_command(source, tmp, self.config)
            stdout_path = tmp if optimizer.use_stdout else None
            code = self._runner(cmd, stdout_path)

            if code != 0 or not tmp.exists() or tmp.stat().st_size == 0:
                return JobResult(
                    JobStatus.UNCHANGED, source, original_size, original_size,
                    message="optimizer produced no smaller output",
                )

            new_size = tmp.stat().st_size
            if original_size - new_size < self.config.min_bytes_saved:
                return JobResult(
                    JobStatus.UNCHANGED, source, original_size, new_size,
                    message="already optimal",
                )

            backup_id = self.backup_store.backup(source)
            os.replace(tmp, source)  # atomic within same directory
            return JobResult(
                JobStatus.OPTIMIZED, source, original_size, new_size,
                backup_id=backup_id,
            )
        finally:
            if tmp.exists():
                tmp.unlink()

    def undo(self, backup_id: str) -> Path:
        return self.backup_store.restore(backup_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_engine.py -v`
Expected: PASS. The 4 injected-runner tests pass unconditionally; `test_real_pngquant_end_to_end` passes if `pngquant` is installed, else SKIPPED.

- [ ] **Step 6: Commit**

```bash
git add src/klop/job.py src/klop/engine.py tests/test_engine.py
git commit -m "Update: add optimization engine with backup and undo

Add OptimizationJob/JobResult/JobStatus plus Engine.optimize(), which
auto-detects media type, runs the selected optimizer into a temp file
via an injectable runner, and atomically replaces the original only
when the result clears min_bytes_saved (backing it up first). Add
Engine.undo(). Tests cover skip/optimize/unchanged/fail paths and a
real pngquant end-to-end run gated on the tool being installed.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: CLI entrypoint

**Files:**
- Create: `src/klop/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config`, `default_config_path`, `detect_capabilities`, `BackupStore`, `Engine`, `OptimizationJob`, `JobStatus`.
- Produces:
  - `klop.cli.main(argv: list[str] | None = None) -> int` — exit code (0 success; 1 on per-file error).
  - Subcommands:
    - `klop optimize <file>...` — optimize each file, print one line per file (`optimized`/`unchanged`/`skipped` with sizes and backup id).
    - `klop undo <backup_id>` — restore an original.
    - `klop caps` — print detected optimizer tools and their paths.
  - Backup root: `~/.local/share/klop/backups` (via `_backup_root()`; overridable with env `KLOP_BACKUP_DIR` for tests).

- [ ] **Step 1: Write the failing test `tests/test_cli.py`**

```python
import shutil

from klop.cli import main


def test_caps_lists_tools(capsys, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    rc = main(["caps"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pngquant" in out
    assert "/usr/bin/pngquant" in out


def test_optimize_reports_skipped(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(shutil, "which", lambda name: None)  # no tools
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    rc = main(["optimize", str(f)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "skipped" in out.lower()
    assert "a.png" in out


def test_optimize_missing_file_errors(tmp_path, capsys):
    rc = main(["optimize", str(tmp_path / "ghost.png")])
    assert rc == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_undo_restores(tmp_path, capsys, monkeypatch):
    from klop.backup import BackupStore

    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
    f = tmp_path / "a.png"
    f.write_bytes(b"ORIGINAL")
    store = BackupStore(tmp_path / "backups")
    bid = store.backup(f)
    f.write_bytes(b"CHANGED")

    rc = main(["undo", bid])
    assert rc == 0
    assert f.read_bytes() == b"ORIGINAL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.cli'`.

- [ ] **Step 3: Write `src/klop/cli.py`**

```python
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .backup import BackupStore
from .capabilities import KNOWN_TOOLS, detect_capabilities
from .config import load_config
from .engine import Engine
from .job import JobStatus, OptimizationJob


def _backup_root() -> Path:
    override = os.environ.get("KLOP_BACKUP_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "klop" / "backups"


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n / 1024:.1f}{unit}"
        n /= 1024
    return f"{n:.0f}B"


def _build_engine() -> Engine:
    return Engine(
        config=load_config(),
        backup_store=BackupStore(_backup_root()),
        capabilities=detect_capabilities(),
    )


def _cmd_caps(_args) -> int:
    caps = detect_capabilities(KNOWN_TOOLS)
    for name in KNOWN_TOOLS:
        path = caps.get(name)
        print(f"{name:12} {path or '(not found)'}")
    return 0


def _cmd_optimize(args) -> int:
    engine = _build_engine()
    exit_code = 0
    for raw in args.files:
        path = Path(raw)
        if not path.exists():
            print(f"error: file not found: {path}", file=sys.stderr)
            exit_code = 1
            continue
        result = engine.optimize(OptimizationJob(source_path=path))
        if result.status == JobStatus.OPTIMIZED:
            print(
                f"optimized {path.name}: "
                f"{_human(result.original_size)} -> {_human(result.new_size)} "
                f"(saved {_human(result.saved_bytes)}, undo id {result.backup_id})"
            )
        else:
            print(f"{result.status.value} {path.name}: {result.message}")
    return exit_code


def _cmd_undo(args) -> int:
    store = BackupStore(_backup_root())
    try:
        restored = store.restore(args.backup_id)
    except KeyError:
        print(f"error: unknown backup id: {args.backup_id}", file=sys.stderr)
        return 1
    print(f"restored {restored}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="klop")
    sub = parser.add_subparsers(dest="command", required=True)

    p_opt = sub.add_parser("optimize", help="optimize one or more files")
    p_opt.add_argument("files", nargs="+")
    p_opt.set_defaults(func=_cmd_optimize)

    p_undo = sub.add_parser("undo", help="restore a backed-up original")
    p_undo.add_argument("backup_id")
    p_undo.set_defaults(func=_cmd_undo)

    p_caps = sub.add_parser("caps", help="show detected optimizer tools")
    p_caps.set_defaults(func=_cmd_caps)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest -v`
Expected: all tests pass (real-pngquant test SKIPPED if the tool is absent).

- [ ] **Step 6: Smoke-test the real CLI**

Run:
```bash
.venv/bin/klop caps
.venv/bin/klop optimize tests/does_not_exist.png; echo "exit=$?"
```
Expected: `caps` prints the tool table; the optimize line prints `error: file not found` to stderr and `exit=1`.

- [ ] **Step 7: Commit**

```bash
git add src/klop/cli.py tests/test_cli.py
git commit -m "Update: add klop CLI entrypoint

Add the argparse-based CLI with optimize/undo/caps subcommands wiring
config, capability detection, BackupStore, and Engine together. This
is the headless entrypoint that M5's Dolphin service menu will reuse.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (M0 scope):**
- Project scaffold → Task 1. ✓
- `config.toml` loader → Task 2. ✓
- Optimizer capability detection → Task 3. ✓
- BackupStore + undo → Task 4 (+ Engine.undo in Task 6). ✓
- PNG/JPEG optimizer path → Task 5. ✓
- Engine (backup → run → smaller-only replace) → Task 6. ✓
- `klop optimize <file>` CLI entrypoint → Task 7. ✓
- Tests: smaller-or-unchanged, backup+undo → Task 6 tests. ✓
- Capability detection via stubbed PATH → Task 3 tests. ✓
- **Deferred (documented):** async Queue and PySide6 → M1 (needs the Qt event loop; M0 is headless by design).

**Placeholder scan:** No TBD/TODO/"add error handling" — every code and test step contains complete code. ✓

**Type consistency:** `OptimizationJob.source_path`, `JobResult.status/saved_bytes`, `JobStatus` members, `Optimizer.build_command/use_stdout`, `select_optimizer(media_type, caps, cfg)`, `Engine(config, backup_store, capabilities, runner)`, `BackupStore.backup/restore/prune`, and `detect_capabilities` dict shape are used identically across the tasks that define and consume them. ✓
