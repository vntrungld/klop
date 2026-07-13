from pathlib import Path

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
    tray, queue, notifier = build_daemon(qapp, engine=engine, backend=backend)

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
    tray, queue, notifier = build_daemon(qapp, engine=engine, backend=backend)

    queue.submit([tmp_path / "z.png"])
    queue.wait_for_done(5000)
    qapp.processEvents()

    nid = backend.sent[0][0]
    backend.on_action(nid, "undo")

    assert engine.undone == ["b1"]
