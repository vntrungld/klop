# Klop M2 — Clipboard Auto-Optimize Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Watch the clipboard for raw image data, optimize it via pngquant off the GUI thread, write the smaller image back, and offer an Undo that restores the original — without ever re-optimizing our own output.

**Architecture:** A new `clipboard.py` provides byte-level PNG optimization (`optimize_image_bytes`) and a `ClipboardWatcher` QObject that guards against loops with a content-hash LRU, offloads optimization to a worker thread, and writes results back via `QMimeData`. M1's `Notifier` undo is generalized from a file `backup_id` to a per-notification callback so clipboard-undo reuses it. The M0 engine and optimizer registry are reused unchanged.

**Tech Stack:** Python 3.11+, PySide6 (`QtCore`/`QtGui`: QClipboard, QMimeData, QImage, QBuffer, QThreadPool). Optimization shells out to `pngquant` via the M0 registry. No new dependencies.

## Global Constraints

- **Python 3.11+, PySide6.** No new runtime dependencies beyond M1 (PySide6 + `gdbus`).
- **The headless CLI must stay Qt-free.** `clipboard.py` imports Qt and is daemon-only; do not import it from `cli.py` at module scope.
- **Reuse M0 unchanged:** do not modify `engine.py`, `backup.py`, `optimizers.py`, `media.py`, `job.py`. M2 reuses `select_optimizer`, `_default_runner`, `MediaType`, `Config`.
- **Raw bitmap image data only** — ignore text and `text/uri-list` (copied files).
- **Content-hash guard:** before optimizing, skip if the image's hash is in a bounded "seen" LRU; after writing back, both the original and optimized hashes are in the LRU so our own write is ignored. LRU is bounded (32 entries).
- **Write-back via `QMimeData`** setting `image/png` to the exact optimized bytes (plus `setImageData` when the bytes are a valid image), so a paste receives the smaller bytes.
- **Only replace if smaller** by at least `Config.min_bytes_saved`; otherwise leave the clipboard untouched and send no notification.
- **Clipboard reads/writes on the GUI thread; the pngquant subprocess on a worker thread.**
- **Gated by the tray Enabled toggle and a `clipboard_watch` config flag** (default True).
- **Commit message format:** first line `{Action}: {desc}` where Action ∈ {Update, Fix, WIP, Hotfix}, imperative, <72 chars; blank line; body; `Co-Authored-By: Claude <noreply@anthropic.com>` trailer. Commit with `git -c user.name='Klop' -c user.email='vn.trungld@gmail.com' commit`.
- **Dev commands:** `.venv/bin/pytest`, `.venv/bin/pip`. Current suite baseline: 65 tests passing.

## File Structure

```
src/klop/
├── clipboard.py     # NEW: image_to_png_bytes, content_hash, optimize_image_bytes,
│                    #      ClipboardResult, ClipboardWatcher  (daemon-only; imports Qt)
├── notifier.py      # MODIFY: generalize undo to a per-notification callback (add notify())
├── app.py           # MODIFY: extract record_saved() from _on_job_done
├── config.py        # MODIFY: add clipboard_watch flag
└── daemon.py        # MODIFY: construct + wire the ClipboardWatcher; return 4-tuple
tests/
├── test_clipboard.py  # NEW
├── test_notifier.py   # MODIFY: add generic-notify() tests (existing tests stay green)
├── test_app.py        # MODIFY: add record_saved tests
├── test_config.py     # MODIFY: add clipboard_watch tests
└── test_daemon.py     # MODIFY: 4-tuple unpack + clipboard-wiring tests
```

---

## Task 1: Generalize the Notifier undo to a per-notification callback

**Files:**
- Modify: `src/klop/notifier.py` (the `Notifier` class only; leave `DBusNotificationBackend` untouched)
- Modify: `tests/test_notifier.py` (add new tests; existing tests stay unchanged and green)

**Interfaces:**
- Consumes: `klop.format.human_size`, `percent_saved`; `klop.job.JobResult`, `JobStatus`.
- Produces:
  - `Notifier.__init__(self, backend, undo_fn=None, icon="", parent=None)` — `undo_fn` now optional.
  - `Notifier.notify(self, summary, body, *, undo=None, undo_confirm=None, icon=None) -> int` —
    sends a notification; if `undo` (a zero-arg callable) is given, attaches the `("undo","Undo")`
    action and stores `notification_id → (undo, undo_confirm)`. Returns the notification id.
  - `notify_result(self, result)` — unchanged behavior, now implemented via `notify()`.
  - On `on_action(id, "undo")` for a known id: calls the stored callback, forgets the id, and (if
    `undo_confirm` is set) sends `undo_confirm` as a follow-up. Unknown id / non-"undo" key → no-op.

- [ ] **Step 1: Write the failing tests (append to `tests/test_notifier.py`)**

```python
def test_generic_notify_with_undo_callback_invokes_it():
    backend = FakeBackend()
    notifier = Notifier(backend=backend)  # no undo_fn needed
    called = []
    nid = notifier.notify("Clipboard image", "1.0KB → 0.4KB (-60%)",
                          undo=lambda: called.append("undone"),
                          undo_confirm="Restored image to clipboard")

    sent_id, summary, body, actions, _ = backend.sent[0]
    assert sent_id == nid
    assert ("undo", "Undo") in actions
    backend.on_action(nid, "undo")
    assert called == ["undone"]
    # undo_confirm follow-up was sent
    assert any("Restored image to clipboard" in s or "Restored image to clipboard" in b
               for _, s, b, _, _ in backend.sent[1:])


def test_generic_notify_without_undo_has_no_action():
    backend = FakeBackend()
    notifier = Notifier(backend=backend)
    notifier.notify("hello", "world")
    _, _, _, actions, _ = backend.sent[0]
    assert actions == []


def test_generic_notify_undo_is_one_shot():
    backend = FakeBackend()
    notifier = Notifier(backend=backend)
    calls = []
    nid = notifier.notify("s", "b", undo=lambda: calls.append(1))
    backend.on_action(nid, "undo")
    backend.on_action(nid, "undo")  # second time: id already forgotten
    assert calls == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_notifier.py -k generic -v`
Expected: FAIL — `Notifier` has no `notify` method (AttributeError), and `Notifier(backend=backend)` fails because `undo_fn` is currently required.

- [ ] **Step 3: Rewrite the `Notifier` class in `src/klop/notifier.py`**

Replace the entire `Notifier` class (lines 24-62, from `class Notifier(QObject):` through the end of `_on_closed`) with:

```python
class Notifier(QObject):
    """Turns results into desktop notifications and handles the Undo action.

    Undo is a per-notification callback, so both file-restore (M1) and
    clipboard-restore (M2) go through the same path."""

    def __init__(self, backend, undo_fn: Callable[[str], object] | None = None,
                 icon: str = "", parent=None):
        super().__init__(parent)
        self._backend = backend
        self._undo_fn = undo_fn
        self._icon = icon
        # notification id -> (undo_callback, undo_confirm_text_or_None)
        self._undo_map: dict[int, tuple[Callable[[], object], str | None]] = {}
        backend.on_action = self._on_action
        backend.on_closed = self._on_closed

    def notify(self, summary: str, body: str, *,
               undo: Callable[[], object] | None = None,
               undo_confirm: str | None = None,
               icon: str | None = None) -> int:
        actions = [("undo", "Undo")] if undo is not None else []
        nid = self._backend.send(summary, body, actions,
                                 self._icon if icon is None else icon)
        if undo is not None:
            self._undo_map[nid] = (undo, undo_confirm)
        return nid

    def notify_result(self, result: JobResult) -> None:
        name = result.path.name
        if result.status == JobStatus.OPTIMIZED and result.backup_id:
            body = (
                f"{human_size(result.original_size)} → "
                f"{human_size(result.new_size)} "
                f"(-{percent_saved(result.original_size, result.new_size)}%)"
            )
            backup_id = result.backup_id
            self.notify(name, body,
                        undo=lambda: self._undo_fn(backup_id) if self._undo_fn else None,
                        undo_confirm=f"Restored {name}")
        elif result.status == JobStatus.ERROR:
            self.notify(name, f"Optimization failed: {result.message}")
        # UNCHANGED / SKIPPED: intentionally silent

    def _on_action(self, notification_id: int, action_key: str) -> None:
        if action_key != "undo":
            return
        entry = self._undo_map.pop(notification_id, None)
        if entry is None:
            return
        undo, undo_confirm = entry
        undo()
        if undo_confirm is not None:
            self._backend.send(undo_confirm, undo_confirm, [], self._icon)

    def _on_closed(self, notification_id: int) -> None:
        self._undo_map.pop(notification_id, None)
```

- [ ] **Step 4: Run the notifier tests to verify all pass (old + new)**

Run: `.venv/bin/pytest tests/test_notifier.py -v`
Expected: PASS. The existing M1 tests (undo dispatch, "Restored photo.jpg" follow-up, unknown id, closed-forgets, unchanged/skipped silent, error warning) still pass because `notify_result` preserves behavior; the 3 new generic tests pass.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (68 = 65 + 3).

- [ ] **Step 6: Commit**

```bash
git add src/klop/notifier.py tests/test_notifier.py
git commit -m "Update: generalize notifier undo to a per-notification callback

Add Notifier.notify(summary, body, undo=..., undo_confirm=...) storing a
zero-arg undo callback per notification, and reimplement notify_result on
top of it (M1 file-undo behavior and the Restored follow-up preserved).
This lets clipboard-undo reuse the same path. undo_fn is now optional.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Byte-level image optimization (`clipboard.py`)

**Files:**
- Create: `src/klop/clipboard.py`
- Test: `tests/test_clipboard.py`

**Interfaces:**
- Consumes: `klop.media.MediaType`, `klop.optimizers.select_optimizer`,
  `klop.engine._default_runner`, `klop.config.Config`.
- Produces:
  - `clip.image_to_png_bytes(image: QImage) -> bytes` — serialize a QImage to PNG bytes.
  - `clip.content_hash(png_bytes: bytes) -> str` — sha1 hex digest.
  - `clip.optimize_image_bytes(png_bytes, config, capabilities, runner=None) -> bytes | None` —
    optimize PNG bytes; return the smaller bytes or `None` (no optimizer / not smaller / failure).
    `runner(cmd, stdout_path) -> int` is injectable (defaults to the engine's `_default_runner`).

- [ ] **Step 1: Write the failing test `tests/test_clipboard.py`**

```python
from pathlib import Path

import pytest

from klop.clipboard import content_hash, image_to_png_bytes, optimize_image_bytes
from klop.config import Config


def test_content_hash_stable_and_distinct():
    assert content_hash(b"abc") == content_hash(b"abc")
    assert content_hash(b"abc") != content_hash(b"abd")


def test_image_to_png_bytes_roundtrip(qapp):
    from PySide6.QtGui import QImage

    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(0xFF0000)
    data = image_to_png_bytes(img)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    reloaded = QImage.fromData(data, "PNG")
    assert not reloaded.isNull()
    assert reloaded.width() == 4


def test_optimize_returns_smaller_bytes():
    def runner(cmd, stdout_path):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"y" * 10)
        return 0

    caps = {"pngquant": "/usr/bin/pngquant"}
    result = optimize_image_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000, Config(), caps, runner=runner)
    assert result is not None
    assert len(result) < 1008


def test_optimize_returns_none_when_not_smaller():
    def runner(cmd, stdout_path):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000)  # same size
        return 0

    caps = {"pngquant": "/usr/bin/pngquant"}
    assert optimize_image_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000, Config(), caps, runner=runner) is None


def test_optimize_returns_none_without_optimizer():
    def runner(cmd, stdout_path):
        raise AssertionError("runner must not be called when no optimizer is available")

    assert optimize_image_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100, Config(), {"pngquant": None}, runner=runner) is None


def test_optimize_returns_none_on_runner_failure():
    def runner(cmd, stdout_path):
        return 99  # pngquant "quality not met", writes nothing

    caps = {"pngquant": "/usr/bin/pngquant"}
    assert optimize_image_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100, Config(), caps, runner=runner) is None


@pytest.mark.skipif(__import__("shutil").which("pngquant") is None, reason="pngquant not installed")
def test_optimize_real_pngquant(qapp):
    from PySide6.QtGui import QImage

    img = QImage(256, 256, QImage.Format.Format_ARGB32)
    for y in range(256):
        for x in range(256):
            img.setPixel(x, y, (0xFF << 24) | (x << 16) | (y << 8) | ((x * y) % 256))
    png = image_to_png_bytes(img)
    result = optimize_image_bytes(png, Config(), {"pngquant": __import__("shutil").which("pngquant")})
    # Either it shrank (bytes) or it couldn't beat min_bytes_saved (None) — both are valid.
    assert result is None or len(result) < len(png)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_clipboard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.clipboard'`.

- [ ] **Step 3: Create `src/klop/clipboard.py`**

```python
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

from .config import Config
from .engine import _default_runner
from .media import MediaType
from .optimizers import select_optimizer


def image_to_png_bytes(image: QImage) -> bytes:
    """Serialize a QImage to PNG bytes."""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def content_hash(png_bytes: bytes) -> str:
    """Stable content key for loop-prevention."""
    return hashlib.sha1(png_bytes).hexdigest()


def optimize_image_bytes(png_bytes, config: Config, capabilities, runner=None) -> bytes | None:
    """Optimize PNG bytes, returning the smaller bytes or None (no optimizer,
    not smaller, or failure). No file backup — there is no persistent original."""
    optimizer = select_optimizer(MediaType.PNG, capabilities, config)
    if optimizer is None:
        return None
    run = runner or _default_runner
    original_size = len(png_bytes)
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "in.png"
        src.write_bytes(png_bytes)
        out = Path(tmpdir) / "out.png"
        cmd = optimizer.build_command(src, out, config)
        stdout_path = out if optimizer.use_stdout else None
        code = run(cmd, stdout_path)
        if code != 0 or not out.exists() or out.stat().st_size == 0:
            return None
        new_bytes = out.read_bytes()
    if original_size - len(new_bytes) < config.min_bytes_saved:
        return None
    return new_bytes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_clipboard.py -v`
Expected: PASS (7 passed, or 6 passed + 1 skipped if pngquant is absent — it is installed here, so 7 pass).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (75 = 68 + 7).

- [ ] **Step 6: Commit**

```bash
git add src/klop/clipboard.py tests/test_clipboard.py
git commit -m "Update: add byte-level PNG optimization for the clipboard

Add clipboard.py with image_to_png_bytes, content_hash, and
optimize_image_bytes — a bytes-in/bytes-out PNG optimizer that reuses the
M0 optimizer registry and default runner, returning smaller bytes only
when the result beats min_bytes_saved. No file backup (clipboard images
have no persistent original).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: ClipboardWatcher (`clipboard.py`)

**Files:**
- Modify: `src/klop/clipboard.py` (append `ClipboardResult` and `ClipboardWatcher`)
- Test: `tests/test_clipboard.py` (append watcher tests)

**Interfaces:**
- Consumes: `image_to_png_bytes`, `content_hash` (this module); a `clipboard` object exposing
  `dataChanged` (signal), `mimeData() -> QMimeData`, `setMimeData(QMimeData)`; an
  `optimize_fn(png_bytes) -> bytes | None`.
- Produces:
  - `clip.ClipboardResult` — dataclass `original_size: int`, `new_size: int`, `undo_token: str`;
    property `saved_bytes = max(0, original_size - new_size)`.
  - `clip.ClipboardWatcher(clipboard, optimize_fn, parent=None)` — a `QObject` with:
    - `optimized = Signal(object)` (carries a `ClipboardResult`).
    - `enabled: bool` attribute (default True) — when False, `dataChanged` is ignored.
    - `undo(token: str) -> None` — restore the stashed original bytes to the clipboard.
    - `wait_for_done(msec=-1) -> bool` — for tests/shutdown (waits on the worker pool).

- [ ] **Step 1: Write the failing tests (append to `tests/test_clipboard.py`)**

```python
from PySide6.QtCore import QByteArray, QMimeData, QObject, Signal

from klop.clipboard import ClipboardResult, ClipboardWatcher


class FakeClipboard(QObject):
    dataChanged = Signal()

    def __init__(self):
        super().__init__()
        self._md = QMimeData()

    def mimeData(self):
        return self._md

    def setMimeData(self, md):
        self._md = md
        self.dataChanged.emit()


def _png_mime(data: bytes) -> QMimeData:
    md = QMimeData()
    md.setData("image/png", QByteArray(data))
    return md


_ORIGINAL = b"\x89PNG\r\n\x1a\n" + b"x" * 1000
_SMALLER = b"\x89PNG\r\n\x1a\n" + b"y" * 10


def test_watcher_optimizes_and_writes_back(qapp):
    clip = FakeClipboard()
    calls = []

    def opt(data):
        calls.append(data)
        return _SMALLER

    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=opt)
    results = []
    watcher.optimized.connect(results.append)

    clip.setMimeData(_png_mime(_ORIGINAL))
    watcher.wait_for_done(5000)
    qapp.processEvents()

    assert calls == [_ORIGINAL]  # optimized exactly once (loop-prevented on write-back)
    assert len(results) == 1
    assert results[0].original_size == len(_ORIGINAL)
    assert results[0].new_size == len(_SMALLER)
    assert bytes(clip.mimeData().data("image/png")) == _SMALLER


def test_watcher_skips_already_seen(qapp):
    clip = FakeClipboard()
    calls = []
    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=lambda d: (calls.append(d), _SMALLER)[1])
    watcher.optimized.connect(lambda r: None)

    clip.setMimeData(_png_mime(_ORIGINAL))
    watcher.wait_for_done(5000)
    qapp.processEvents()
    calls.clear()

    clip.setMimeData(_png_mime(_ORIGINAL))  # same original again — hash already seen
    watcher.wait_for_done(5000)
    qapp.processEvents()
    assert calls == []


def test_watcher_disabled_does_not_optimize(qapp):
    clip = FakeClipboard()
    calls = []
    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=lambda d: (calls.append(d), _SMALLER)[1])
    watcher.enabled = False

    clip.setMimeData(_png_mime(_ORIGINAL))
    watcher.wait_for_done(5000)
    qapp.processEvents()
    assert calls == []


def test_watcher_no_change_when_optimize_returns_none(qapp):
    clip = FakeClipboard()
    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=lambda d: None)
    results = []
    watcher.optimized.connect(results.append)

    clip.setMimeData(_png_mime(_ORIGINAL))
    watcher.wait_for_done(5000)
    qapp.processEvents()

    assert results == []
    assert bytes(clip.mimeData().data("image/png")) == _ORIGINAL


def test_watcher_undo_restores_original(qapp):
    clip = FakeClipboard()
    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=lambda d: _SMALLER)
    results = []
    watcher.optimized.connect(results.append)

    clip.setMimeData(_png_mime(_ORIGINAL))
    watcher.wait_for_done(5000)
    qapp.processEvents()

    token = results[0].undo_token
    watcher.undo(token)
    assert bytes(clip.mimeData().data("image/png")) == _ORIGINAL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_clipboard.py -k watcher -v`
Expected: FAIL — `ClipboardWatcher` / `ClipboardResult` are not defined yet (ImportError).

- [ ] **Step 3: Append to `src/klop/clipboard.py`**

Add these imports to the existing import block at the top of the file:

```python
from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
```

Then append at the end of the file:

```python
_SEEN_MAX = 32


@dataclass
class ClipboardResult:
    original_size: int
    new_size: int
    undo_token: str

    @property
    def saved_bytes(self) -> int:
        return max(0, self.original_size - self.new_size)


class _ClipRunnable(QRunnable):
    def __init__(self, watcher: "ClipboardWatcher", png_bytes: bytes, digest: str):
        super().__init__()
        self._watcher = watcher
        self._png = png_bytes
        self._digest = digest

    def run(self) -> None:
        try:
            optimized = self._watcher._optimize_fn(self._png)
        except Exception:  # noqa: BLE001 - never crash the pool
            optimized = None
        self._watcher._result_ready.emit(self._png, self._digest, optimized)


class ClipboardWatcher(QObject):
    """Watches the clipboard for image data, optimizes it off the GUI thread,
    and writes the smaller result back — guarding against re-optimizing our own
    output with a bounded content-hash set."""

    optimized = Signal(object)  # ClipboardResult
    _result_ready = Signal(object, str, object)  # (original_bytes, digest, optimized|None)

    def __init__(self, clipboard, optimize_fn, parent=None):
        super().__init__(parent)
        self._clipboard = clipboard
        self._optimize_fn = optimize_fn
        self.enabled = True
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(1)
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._undo_store: dict[str, bytes] = {}
        self._undo_counter = 0
        clipboard.dataChanged.connect(self._on_changed)
        self._result_ready.connect(self._on_result_ready)

    def wait_for_done(self, msec: int = -1) -> bool:
        return self._pool.waitForDone(msec)

    def undo(self, token: str) -> None:
        original = self._undo_store.pop(token, None)
        if original is None:
            return
        self._remember(content_hash(original))  # restoring must not re-trigger optimize
        self._set_clipboard_png(original)

    def _remember(self, digest: str) -> None:
        self._seen[digest] = None
        self._seen.move_to_end(digest)
        while len(self._seen) > _SEEN_MAX:
            self._seen.popitem(last=False)

    def _read_png(self, md) -> bytes | None:
        if md is None:
            return None
        if md.hasFormat("image/png"):
            data = bytes(md.data("image/png"))
            return data or None
        if md.hasImage():
            image = md.imageData()
            if isinstance(image, QImage) and not image.isNull():
                return image_to_png_bytes(image)
        return None

    def _set_clipboard_png(self, png_bytes: bytes) -> None:
        md = QMimeData()
        md.setData("image/png", QByteArray(png_bytes))
        image = QImage.fromData(QByteArray(png_bytes), "PNG")
        if not image.isNull():
            md.setImageData(image)
        self._clipboard.setMimeData(md)

    def _on_changed(self) -> None:
        if not self.enabled:
            return
        png = self._read_png(self._clipboard.mimeData())
        if not png:
            return
        digest = content_hash(png)
        if digest in self._seen:
            return
        self._pool.start(_ClipRunnable(self, png, digest))

    def _on_result_ready(self, original: bytes, digest: str, optimized) -> None:
        self._remember(digest)  # don't reprocess this exact input
        if optimized is None:
            return
        self._remember(content_hash(optimized))
        self._undo_counter += 1
        token = str(self._undo_counter)
        self._undo_store[token] = original
        self._set_clipboard_png(optimized)
        self.optimized.emit(ClipboardResult(len(original), len(optimized), token))
```

Note: `QMimeData` and `QByteArray` are already imported at the top of the file from Task 2's import block (`from PySide6.QtCore import QBuffer, QByteArray, QIODevice`) — add `QMimeData` to that line as well.

- [ ] **Step 4: Run the watcher tests to verify they pass**

Run: `.venv/bin/pytest tests/test_clipboard.py -k watcher -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (80 = 75 + 5).

- [ ] **Step 6: Commit**

```bash
git add src/klop/clipboard.py tests/test_clipboard.py
git commit -m "Update: add ClipboardWatcher with loop-prevention and undo

Add ClipboardWatcher: on clipboard image changes it optimizes PNG bytes
on a worker thread and writes the smaller result back, guarding against
re-optimizing its own output (and already-optimized images) with a
bounded content-hash set. Stashes the original for undo(token), which
restores it to the clipboard. Gated by an enabled flag.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Tray `record_saved` + `clipboard_watch` config flag

**Files:**
- Modify: `src/klop/app.py` (extract `record_saved`)
- Modify: `src/klop/config.py` (add `clipboard_watch`)
- Test: `tests/test_app.py` (add `record_saved` tests)
- Test: `tests/test_config.py` (add `clipboard_watch` tests)

**Interfaces:**
- Produces:
  - `TrayApp.record_saved(self, saved_bytes: int) -> None` — adds to the session total and updates
    the `Saved: X` action text. `_on_job_done` calls it for `OPTIMIZED` results; the clipboard path
    calls it too.
  - `Config.clipboard_watch: bool = True`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
def test_record_saved_accumulates_total_and_updates_text(qapp):
    queue = FakeQueue()
    tray = TrayApp(queue=queue, notifier=FakeNotifier(), pick_files=lambda: [])

    tray.record_saved(5000)
    tray.record_saved(3000)

    assert tray.saved_total() == 8000
    assert "Saved:" in tray.saved_action.text()
    assert "7.8KB" in tray.saved_action.text()  # 8000 bytes -> 7.8KB
```

Append to `tests/test_config.py`:

```python
def test_clipboard_watch_defaults_true(tmp_path):
    from klop.config import load_config

    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.clipboard_watch is True


def test_clipboard_watch_can_be_disabled(tmp_path):
    from klop.config import load_config

    p = tmp_path / "config.toml"
    p.write_text("clipboard_watch = false\n")
    assert load_config(p).clipboard_watch is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_app.py -k record_saved tests/test_config.py -k clipboard_watch -v`
Expected: FAIL — `TrayApp` has no `record_saved` (AttributeError) and `Config` has no `clipboard_watch` (AttributeError).

- [ ] **Step 3: Add `clipboard_watch` to `src/klop/config.py`**

In the `Config` dataclass, add the field after `backup_max_bytes`:

```python
    clipboard_watch: bool = True
```

- [ ] **Step 4: Extract `record_saved` in `src/klop/app.py`**

Replace the `_on_job_done` method (lines 88-92) with:

```python
    def record_saved(self, saved_bytes: int) -> None:
        self._saved_total += saved_bytes
        self.saved_action.setText(f"Saved: {human_size(self._saved_total)}")

    def _on_job_done(self, result: JobResult) -> None:
        if result.status == JobStatus.OPTIMIZED:
            self.record_saved(result.saved_bytes)
        self._notifier.notify_result(result)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_app.py -k record_saved tests/test_config.py -k clipboard_watch -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (83 = 80 + 3).

- [ ] **Step 7: Commit**

```bash
git add src/klop/app.py src/klop/config.py tests/test_app.py tests/test_config.py
git commit -m "Update: add TrayApp.record_saved and clipboard_watch config

Extract the tray savings-total update into a public record_saved() so both
the file-optimize and clipboard paths feed one total, and add a
clipboard_watch config flag (default true) to let users disable clipboard
watching.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Wire the ClipboardWatcher into the daemon

**Files:**
- Modify: `src/klop/daemon.py` (construct + wire the watcher; return a 4-tuple)
- Test: `tests/test_daemon.py` (update 3-tuple unpacks to 4-tuple; add clipboard-wiring tests)

**Interfaces:**
- Consumes: `ClipboardWatcher`, `optimize_image_bytes` (`clipboard.py`); `detect_capabilities`
  (`capabilities.py`); `human_size`, `percent_saved` (`format.py`); `Notifier.notify`;
  `TrayApp.record_saved`, `TrayApp.enabled_action`; `Config.clipboard_watch`, `Config.concurrency`.
- Produces:
  - `build_daemon(app, *, engine=None, backend=None, clipboard=None) -> (TrayApp, OptimizationQueue,
    Notifier, ClipboardWatcher | None)` — now returns a 4-tuple; the watcher is `None` when
    `config.clipboard_watch` is False. When present, its `optimized` signal updates the tray total
    and fires a notification with a clipboard-undo; the tray Enabled toggle sets `watcher.enabled`.

- [ ] **Step 1: Update the existing tests + write new failing tests in `tests/test_daemon.py`**

Change the two existing tests' unpacking from `tray, queue, notifier = build_daemon(...)` to
`tray, queue, notifier, _watcher = build_daemon(...)`. Then append:

```python
from klop.clipboard import ClipboardResult


def test_build_daemon_wires_clipboard_watcher(qapp, monkeypatch):
    engine = FakeEngine()
    backend = FakeBackend()

    from PySide6.QtCore import QMimeData, QObject, Signal

    class FakeClipboard(QObject):
        dataChanged = Signal()

        def mimeData(self):
            return QMimeData()

        def setMimeData(self, md):
            pass

    tray, queue, notifier, watcher = build_daemon(
        qapp, engine=engine, backend=backend, clipboard=FakeClipboard()
    )
    assert watcher is not None

    # A clipboard optimization result should update the tray total and notify.
    watcher.optimized.emit(ClipboardResult(original_size=1000, new_size=250, undo_token="1"))

    assert tray.saved_total() == 750
    assert len(backend.sent) == 1
    _, summary, body, actions, _ = backend.sent[0]
    assert ("undo", "Undo") in actions
    assert "750" in body or "%" in body


def test_build_daemon_enabled_toggle_controls_watcher(qapp):
    from PySide6.QtCore import QMimeData, QObject, Signal

    class FakeClipboard(QObject):
        dataChanged = Signal()

        def mimeData(self):
            return QMimeData()

        def setMimeData(self, md):
            pass

    tray, queue, notifier, watcher = build_daemon(
        qapp, engine=FakeEngine(), backend=FakeBackend(), clipboard=FakeClipboard()
    )
    assert watcher.enabled is True
    tray.enabled_action.setChecked(False)  # fires toggled(False)
    assert watcher.enabled is False


def test_build_daemon_no_watcher_when_disabled(qapp, monkeypatch):
    import klop.daemon as daemon_mod
    from klop.config import Config

    monkeypatch.setattr(daemon_mod, "load_config", lambda: Config(clipboard_watch=False))
    tray, queue, notifier, watcher = build_daemon(qapp, engine=FakeEngine(), backend=FakeBackend())
    assert watcher is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_daemon.py -v`
Expected: FAIL — `build_daemon` still returns a 3-tuple (the new 4-tuple unpacks raise ValueError) and does not construct a watcher.

- [ ] **Step 3: Rewrite `src/klop/daemon.py`**

```python
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .app import TrayApp, load_tray_icon
from .capabilities import detect_capabilities
from .cli import _build_engine
from .clipboard import ClipboardWatcher, optimize_image_bytes
from .config import load_config
from .format import human_size, percent_saved
from .notifier import DBusNotificationBackend, Notifier
from .queue import OptimizationQueue


def build_daemon(app, *, engine=None, backend=None, clipboard=None):
    engine = engine or _build_engine()
    config = load_config()
    queue = OptimizationQueue(optimize_fn=engine.optimize, concurrency=config.concurrency)
    backend = backend or DBusNotificationBackend()
    notifier = Notifier(backend=backend, undo_fn=engine.undo)
    tray = TrayApp(queue=queue, notifier=notifier, icon=load_tray_icon())

    watcher = None
    if config.clipboard_watch:
        if clipboard is None:
            from PySide6.QtGui import QGuiApplication

            clipboard = QGuiApplication.clipboard()
        capabilities = detect_capabilities()

        def _optimize(png_bytes):
            return optimize_image_bytes(png_bytes, config, capabilities)

        watcher = ClipboardWatcher(clipboard=clipboard, optimize_fn=_optimize)

        def _on_clipboard_optimized(result):
            tray.record_saved(result.saved_bytes)
            body = (
                f"{human_size(result.original_size)} → "
                f"{human_size(result.new_size)} "
                f"(-{percent_saved(result.original_size, result.new_size)}%)"
            )
            token = result.undo_token
            notifier.notify(
                "Clipboard image",
                body,
                undo=lambda: watcher.undo(token),
                undo_confirm="Restored image to clipboard",
            )

        watcher.optimized.connect(_on_clipboard_optimized)
        tray.enabled_action.toggled.connect(
            lambda checked: setattr(watcher, "enabled", checked)
        )

    return tray, queue, notifier, watcher


def run_daemon() -> int:
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)  # tray-only app; no windows keep it alive
    tray, _queue, _notifier, _watcher = build_daemon(app)
    tray.show()
    return app.exec()
```

- [ ] **Step 4: Run the daemon tests to verify they pass**

Run: `.venv/bin/pytest tests/test_daemon.py -v`
Expected: PASS (the two updated M1 tests + 3 new clipboard tests).

- [ ] **Step 5: Confirm the headless CLI is still Qt-free**

Run: `.venv/bin/python -c "import sys, klop.cli; assert 'PySide6' not in sys.modules; print('cli Qt-free: OK')"`
Expected: prints `cli Qt-free: OK` (daemon.py and clipboard.py import Qt, but cli.py imports them only lazily inside `_cmd_daemon`).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (86 = 83 + 3).

- [ ] **Step 7: Manual smoke test (interactive — perform in a Plasma session)**

Run: `.venv/bin/klop daemon`
Then copy a large screenshot (e.g. via Spectacle) or an image from a browser. Confirm: a
notification appears reporting the savings with an **Undo** button; pasting into an app that saves
the image (or re-copying) yields the smaller image; clicking **Undo** restores the original so the
next paste is the original; toggling the tray **Enabled** off stops clipboard optimization. Note the
outcome in the report. (If not in a graphical session, state that the automated tests cover the
wiring and this step was skipped.)

- [ ] **Step 8: Commit**

```bash
git add src/klop/daemon.py tests/test_daemon.py
git commit -m "Update: wire ClipboardWatcher into the daemon

build_daemon now constructs a ClipboardWatcher (when clipboard_watch is
enabled), routing its optimized results to the tray savings total and a
notification with a clipboard Undo, and binding the Enabled toggle to the
watcher. build_daemon returns a 4-tuple; run_daemon and the daemon tests
are updated accordingly.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Watch clipboard for raw image data → Task 3 (`ClipboardWatcher._on_changed`, `_read_png`). ✓
- Optimize PNG bytes, only if smaller → Task 2 (`optimize_image_bytes`). ✓
- Content-hash loop-prevention (bounded LRU) → Task 3 (`_seen`/`_remember`, tests for write-back & re-copy). ✓
- Write-back via QMimeData (`image/png` + `setImageData`) → Task 3 (`_set_clipboard_png`). ✓
- Optimizer on a worker thread, clipboard on GUI thread → Task 3 (`QThreadPool` + `_result_ready` queued signal). ✓
- Clipboard undo restores original → Task 3 (`undo`), Task 1 (callback undo), Task 5 (wiring). ✓
- Notifier generalized to per-notification callback → Task 1. ✓
- Enabled toggle gates watching → Task 3 (`enabled`), Task 5 (toggle wiring). ✓
- `clipboard_watch` config flag → Task 4, gated in Task 5. ✓
- Feeds one tray "Saved" total → Task 4 (`record_saved`), Task 5 (wiring). ✓
- Reuse M0 registry unchanged; CLI stays Qt-free → Tasks 2/5 (import reuse; Task 5 Step 5 assertion). ✓

**Placeholder scan:** No TBD/TODO; every code and test step is complete. The only non-automated step is the Task 5 interactive smoke test, explicitly marked with a skip path.

**Type consistency:** `Notifier.notify(summary, body, *, undo, undo_confirm, icon)`; `optimize_image_bytes(png_bytes, config, capabilities, runner)`; `ClipboardWatcher(clipboard, optimize_fn)` with `optimized: Signal(object)`, `enabled`, `undo(token)`, `wait_for_done`; `ClipboardResult(original_size, new_size, undo_token)` + `saved_bytes`; `TrayApp.record_saved(saved_bytes)`; `Config.clipboard_watch`; `build_daemon(...) -> (tray, queue, notifier, watcher)` — all used consistently across the tasks that define and consume them.
