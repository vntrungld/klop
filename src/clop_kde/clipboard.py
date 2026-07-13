from __future__ import annotations

import hashlib
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, QObject, QRunnable, QThreadPool, Signal
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
