from clop_kde.daemon import build_daemon
from clop_kde.job import JobResult, JobStatus


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


from clop_kde.clipboard import ClipboardResult


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


def test_build_daemon_no_watcher_when_disabled(qapp, monkeypatch):
    import clop_kde.daemon as daemon_mod
    from clop_kde.config import Config

    monkeypatch.setattr(daemon_mod, "load_config", lambda: Config(clipboard_watch=False))
    d = build_daemon(qapp, engine=FakeEngine(), backend=FakeBackend())
    assert d.watcher is None


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
