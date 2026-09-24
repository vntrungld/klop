from klop.daemon import build_daemon
from klop.job import JobResult, JobStatus


class FakeEngine:
    def __init__(self):
        self.undone = []

    def optimize(self, job):
        return JobResult(JobStatus.OPTIMIZED, job.source_path, 1000, 200, backup_id="b1")

    def undo(self, backup_id):
        self.undone.append(backup_id)


class FakeBackend:
    def __init__(self):
        self.sent = []
        self.on_action = None
        self.on_closed = None
        self._n = 1

    def send(self, summary, body, actions, icon):
        nid = self._n
        self._n += 1
        self.sent.append((nid, summary, body, actions, icon))
        return nid


class FakeOverlay:
    def __init__(self):
        self.shown = []
        self.pending = []
        self.dismissed = 0
        self._pending = False

    def show_result(self, result):
        self.shown.append(result)
        self._pending = False

    def show_pending(self, title, thumbnail_source=None):
        self.pending.append((title, thumbnail_source))
        self._pending = True

    def dismiss(self):
        self.dismissed += 1
        self._pending = False

    def dismiss_if_pending(self):
        if self._pending:
            self.dismiss()


def test_build_daemon_routes_file_result_to_overlay_not_notification(qapp, tmp_path):
    engine = FakeEngine()
    backend = FakeBackend()
    overlay = FakeOverlay()
    d = build_daemon(qapp, engine=engine, backend=backend, overlay=overlay)

    d.queue.submit([tmp_path / "z.png"])
    d.queue.wait_for_done(5000)
    qapp.processEvents()

    assert d.tray.saved_total() == 800  # 1000 - 200
    assert len(overlay.shown) == 1  # file result surfaced as the overlay
    assert backend.sent == []  # NO desktop notification for a file OPTIMIZED result


def test_build_daemon_file_undo_via_overlay(qapp, tmp_path):
    engine = FakeEngine()
    d = build_daemon(qapp, engine=engine, backend=FakeBackend())  # real overlay

    d.queue.submit([tmp_path / "z.png"])
    d.queue.wait_for_done(5000)
    qapp.processEvents()

    d.overlay.undo_button.click()  # the overlay received the result; Undo restores
    assert engine.undone == ["b1"]


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

    d = build_daemon(
        qapp, engine=engine, backend=backend, clipboard=FakeClipboard()
    )
    assert d.watcher is not None

    # A clipboard optimization result should update the tray total and notify.
    d.watcher.optimized.emit(ClipboardResult(original_size=1000, new_size=250, undo_token="1"))

    assert d.tray.saved_total() == 750
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

    d = build_daemon(
        qapp, engine=FakeEngine(), backend=FakeBackend(), clipboard=FakeClipboard()
    )
    assert d.watcher.enabled is True
    d.tray.enabled_action.setChecked(False)  # fires toggled(False)
    assert d.watcher.enabled is False


def _fake_clipboard():
    from PySide6.QtCore import QMimeData, QObject, Signal

    class FakeClipboard(QObject):
        dataChanged = Signal()

        def mimeData(self):
            return QMimeData()

        def setMimeData(self, md):
            pass

    return FakeClipboard()


def test_build_daemon_watcher_disabled_by_config(qapp, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("clipboard_watch = false\n")
    d = build_daemon(
        qapp, engine=FakeEngine(), backend=FakeBackend(),
        clipboard=_fake_clipboard(), config_path=cfg,
    )
    assert d.watcher.enabled is False
    assert d.tray.enabled_action.isChecked() is False


def test_build_daemon_reloads_clipboard_watch_when_config_changes(qapp, tmp_path):
    from klop.config import Config, save_config

    cfg = tmp_path / "config.toml"
    save_config(Config(clipboard_watch=True), cfg)
    d = build_daemon(
        qapp, engine=FakeEngine(), backend=FakeBackend(),
        clipboard=_fake_clipboard(), config_path=cfg,
    )
    assert d.watcher.enabled is True

    save_config(Config(clipboard_watch=False), cfg)  # atomic replace, like `klop config set`
    import time
    deadline = time.monotonic() + 5
    while d.watcher.enabled and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    assert d.watcher.enabled is False

    save_config(Config(clipboard_watch=True), cfg)  # still watched after the replace
    deadline = time.monotonic() + 5
    while not d.watcher.enabled and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    assert d.watcher.enabled is True


def test_build_daemon_wires_job_started_to_overlay_pending(qapp, tmp_path):
    overlay = FakeOverlay()
    d = build_daemon(qapp, engine=FakeEngine(), backend=FakeBackend(), overlay=overlay)
    d.queue.job_started.emit(tmp_path / "z.png")
    qapp.processEvents()
    assert overlay.pending and overlay.pending[0][0] == "z.png"


def test_build_daemon_wires_clipboard_started_and_finished_to_overlay(qapp):
    from PySide6.QtCore import QMimeData, QObject, Signal

    class FakeClipboard(QObject):
        dataChanged = Signal()

        def mimeData(self):
            return QMimeData()

        def setMimeData(self, md):
            pass

    overlay = FakeOverlay()
    d = build_daemon(
        qapp, engine=FakeEngine(), backend=FakeBackend(),
        clipboard=FakeClipboard(), overlay=overlay,
    )
    d.watcher.started.emit(b"\x89PNG\r\n\x1a\n" + b"x" * 10)
    d.watcher.finished.emit()
    qapp.processEvents()
    assert overlay.pending and overlay.pending[0][0] == "Clipboard image"
    assert overlay.dismissed == 1


def test_clipboard_finished_does_not_dismiss_a_file_result_card(qapp):
    """Regression: the shared overlay must not have a file RESULT card torn
    down by an unrelated clipboard job's `finished` signal (whole-branch
    review bug). Interleaving: clipboard started (pending) -> a file result
    is shown on the same overlay -> clipboard finished must NOT dismiss it.
    """
    from PySide6.QtCore import QMimeData, QObject, Signal

    class FakeClipboard(QObject):
        dataChanged = Signal()

        def mimeData(self):
            return QMimeData()

        def setMimeData(self, md):
            pass

    overlay = FakeOverlay()
    d = build_daemon(
        qapp, engine=FakeEngine(), backend=FakeBackend(),
        clipboard=FakeClipboard(), overlay=overlay,
    )
    d.watcher.started.emit(b"\x89PNG\r\n\x1a\n" + b"x" * 10)  # clipboard pending

    file_result = JobResult(JobStatus.OPTIMIZED, "/tmp/z.png", 1000, 200, backup_id="b1")
    d.overlay.show_result(file_result)  # a file result card takes over the shared overlay

    d.watcher.finished.emit()
    qapp.processEvents()

    assert overlay.shown == [file_result]
    assert overlay.dismissed == 0  # clipboard finished must not dismiss the file result card


class FakeHistory:
    def __init__(self):
        self.records = []
        self.undone = []

    def record(self, kind, name, path, original_size, new_size, backup_id=None):
        self.records.append((kind, name, path, original_size, new_size, backup_id))

    def mark_undone(self, backup_id):
        self.undone.append(backup_id)


def test_build_daemon_records_file_result(qapp, tmp_path):
    engine = FakeEngine()
    history = FakeHistory()
    d = build_daemon(qapp, engine=engine, backend=FakeBackend(), history=history)

    d.queue.submit([tmp_path / "z.png"])
    d.queue.wait_for_done(5000)
    qapp.processEvents()

    assert len(history.records) == 1
    kind, name, _path, orig, new, bid = history.records[0]
    assert (kind, name, orig, new, bid) == ("file", "z.png", 1000, 200, "b1")


def test_build_daemon_file_undo_marks_history_undone(qapp, tmp_path):
    engine = FakeEngine()
    history = FakeHistory()
    d = build_daemon(qapp, engine=engine, backend=FakeBackend(), history=history)

    d.queue.submit([tmp_path / "z.png"])
    d.queue.wait_for_done(5000)
    qapp.processEvents()

    d.overlay.undo_button.click()
    assert engine.undone == ["b1"]
    assert history.undone == ["b1"]
