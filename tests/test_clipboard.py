from pathlib import Path

import pytest
from PySide6.QtCore import QByteArray, QMimeData, QObject, Signal

from clop_kde.clipboard import ClipboardResult, ClipboardWatcher, content_hash, image_to_png_bytes, optimize_image_bytes
from clop_kde.config import Config


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


def test_watcher_undo_is_single_slot(qapp):
    # Only the most-recent clipboard optimization is undoable; a new
    # optimization supersedes the previous token.
    clip = FakeClipboard()
    calls = {"n": 0}

    def optimize(png):
        calls["n"] += 1
        return png[:20] + bytes([calls["n"]])  # distinct smaller output each call

    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=optimize)
    results = []
    watcher.optimized.connect(results.append)

    original_one = b"\x89PNG\r\n\x1a\n" + b"one-" + b"z" * 1000
    original_two = b"\x89PNG\r\n\x1a\n" + b"two-" + b"z" * 1000

    clip.setMimeData(_png_mime(original_one))
    watcher.wait_for_done(5000)
    qapp.processEvents()

    clip.setMimeData(_png_mime(original_two))
    watcher.wait_for_done(5000)
    qapp.processEvents()

    assert len(results) == 2
    first_token, second_token = results[0].undo_token, results[1].undo_token
    assert first_token != second_token

    # The old (superseded) token no longer restores anything: this must be a
    # TRUE no-op, not merely "didn't restore original_one" (which a broken
    # token check could satisfy by wrongly restoring the *current* slot).
    optimized_before_stale_undo = bytes(clip.mimeData().data("image/png"))
    watcher.undo(first_token)  # no-op, must not raise
    assert bytes(clip.mimeData().data("image/png")) == optimized_before_stale_undo
    # The current (second) slot must remain intact — untouched by the stale call.
    assert watcher._undo_token == second_token
    assert watcher._undo_original is not None

    # The current token restores the correct original and clears the slot
    # (single-use), so a repeat call with the same token is a no-op.
    watcher.undo(second_token)
    assert bytes(clip.mimeData().data("image/png")) == original_two
    assert watcher._undo_token is None
    assert watcher._undo_original is None

    after_first_restore = bytes(clip.mimeData().data("image/png"))
    watcher.undo(second_token)  # already used, no-op
    assert bytes(clip.mimeData().data("image/png")) == after_first_restore
    assert watcher._undo_token is None
    assert watcher._undo_original is None


def test_watcher_dedupes_repeated_dataChanged_before_worker_finishes(qapp):
    clip = FakeClipboard()
    calls = []

    def opt(data):
        calls.append(data)
        return _SMALLER

    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=opt)
    results = []
    watcher.optimized.connect(results.append)

    # Simulate Klipper: set content without emitting, then emit dataChanged
    # twice in a row before the worker has had a chance to deliver a result.
    clip._md = _png_mime(_ORIGINAL)
    clip.dataChanged.emit()
    clip.dataChanged.emit()

    watcher.wait_for_done(5000)
    qapp.processEvents()

    assert calls == [_ORIGINAL]  # optimized exactly once, not twice
    assert len(results) == 1


def test_watcher_emits_started_and_finished_on_optimize(qapp):
    clip = FakeClipboard()
    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=lambda d: _SMALLER)
    events = []
    watcher.started.connect(lambda data: events.append(("started", bytes(data))))
    watcher.finished.connect(lambda: events.append(("finished",)))

    clip.setMimeData(_png_mime(_ORIGINAL))
    watcher.wait_for_done(5000)
    qapp.processEvents()

    assert ("started", _ORIGINAL) in events
    assert ("finished",) in events
    assert events.index(("started", _ORIGINAL)) < events.index(("finished",))


def test_watcher_emits_finished_even_when_no_gain(qapp):
    clip = FakeClipboard()
    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=lambda d: None)  # no gain
    finished = []
    watcher.finished.connect(lambda: finished.append(1))

    clip.setMimeData(_png_mime(_ORIGINAL))
    watcher.wait_for_done(5000)
    qapp.processEvents()

    assert finished == [1]  # finished fires even though nothing was optimized
