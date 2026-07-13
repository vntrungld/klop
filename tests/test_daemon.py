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


def test_build_daemon_wires_queue_to_tray_and_notifier(qapp, tmp_path):
    engine = FakeEngine()
    backend = FakeBackend()
    tray, queue, notifier, _watcher = build_daemon(qapp, engine=engine, backend=backend)

    # A submitted job should flow: queue worker -> engine.optimize ->
    # job_done -> tray total update + notifier notification.
    queue.submit([tmp_path / "z.png"])
    queue.wait_for_done(5000)
    qapp.processEvents()

    assert tray.saved_total() == 800  # 1000 - 200
    assert len(backend.sent) == 1  # one OPTIMIZED notification with Undo
    assert ("undo", "Undo") in backend.sent[0][3]


def test_build_daemon_undo_action_restores_via_engine(qapp, tmp_path):
    engine = FakeEngine()
    backend = FakeBackend()
    tray, queue, notifier, _watcher = build_daemon(qapp, engine=engine, backend=backend)

    queue.submit([tmp_path / "z.png"])
    queue.wait_for_done(5000)
    qapp.processEvents()

    nid = backend.sent[0][0]
    backend.on_action(nid, "undo")

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
    import clop_kde.daemon as daemon_mod
    from clop_kde.config import Config

    monkeypatch.setattr(daemon_mod, "load_config", lambda: Config(clipboard_watch=False))
    tray, queue, notifier, watcher = build_daemon(qapp, engine=FakeEngine(), backend=FakeBackend())
    assert watcher is None
