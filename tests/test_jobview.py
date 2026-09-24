from types import SimpleNamespace

from jeepney import MessageType

from klop import jobview
from klop.jobview import JobProgress


class FakeConn:
    def __init__(self, fail=()):
        self.calls = []
        self.closed = False
        self.fail = set(fail)

    def send_and_get_reply(self, msg, timeout=None):
        method = msg.header.fields[3]  # HeaderFields.member
        self.calls.append((method, msg.body))
        kind = MessageType.error if method in self.fail else MessageType.method_return
        body = ("/org/kde/jobs/JobView_1",) if method == "requestView" else ()
        return SimpleNamespace(header=SimpleNamespace(message_type=kind), body=body)

    def close(self):
        self.closed = True


def test_progress_reports_files_and_finishes_with_summary(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(jobview, "_connect", lambda: conn)

    job = JobProgress.start(3, icon="klop")
    job.update(1, 3, "b.png")
    assert job.finish("Optimized 3 files") is True

    assert conn.calls == [
        ("requestView", ("Klop", "klop", 0)),
        ("setTotalAmount", (3, "files")),
        ("setInfoMessage", ("Optimizing b.png",)),
        ("setProcessedAmount", (1, "files")),
        ("setPercent", (33,)),
        ("setProcessedAmount", (3, "files")),
        ("setPercent", (100,)),
        ("setInfoMessage", ("Optimized 3 files",)),
        ("terminate", ("",)),
    ]
    assert conn.closed and not job.active


def test_progress_is_a_noop_without_dbus(monkeypatch):
    monkeypatch.setattr(jobview, "_connect", lambda: None)

    job = JobProgress.start(2)
    job.update(0, 2, "a.png")

    assert not job.active
    assert job.finish("done") is False


def test_progress_is_a_noop_when_no_job_tracker_answers(monkeypatch):
    conn = FakeConn(fail={"requestView"})
    monkeypatch.setattr(jobview, "_connect", lambda: conn)

    job = JobProgress.start(2)

    assert not job.active and conn.closed
    assert job.finish("done") is False
