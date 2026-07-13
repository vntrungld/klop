from pathlib import Path

from clop_kde.job import JobResult, JobStatus
from clop_kde.notifier import DBusNotificationBackend, Notifier


class FakeBackend:
    def __init__(self):
        self.sent = []  # (id, summary, body, actions, icon)
        self.on_action = None
        self.on_closed = None
        self._next_id = 1

    def send(self, summary, body, actions, icon):
        nid = self._next_id
        self._next_id += 1
        self.sent.append((nid, summary, body, actions, icon))
        return nid


def _optimized(path, orig, new, backup_id="b1"):
    return JobResult(JobStatus.OPTIMIZED, path, orig, new, backup_id=backup_id)


def test_optimized_result_sends_notification_with_undo_action():
    backend = FakeBackend()
    notifier = Notifier(backend=backend, undo_fn=lambda bid: None)
    notifier.notify_result(_optimized(Path("/tmp/photo.jpg"), 8579, 3431))

    assert len(backend.sent) == 1
    nid, summary, body, actions, icon = backend.sent[0]
    assert "photo.jpg" in summary
    assert "60%" in body  # 8579 -> 3431 is -60%
    assert ("undo", "Undo") in actions


def test_undo_action_invokes_undo_fn_and_sends_restored():
    backend = FakeBackend()
    undone = []
    notifier = Notifier(backend=backend, undo_fn=lambda bid: undone.append(bid))
    notifier.notify_result(_optimized(Path("/tmp/photo.jpg"), 1000, 400, backup_id="B7"))

    nid = backend.sent[0][0]
    backend.on_action(nid, "undo")

    assert undone == ["B7"]
    # a follow-up "Restored ..." notification was sent
    assert any("Restored" in s or "Restored" in b for _, s, b, _, _ in backend.sent[1:])
    assert any("photo.jpg" in s or "photo.jpg" in b for _, s, b, _, _ in backend.sent[1:])


def test_unknown_notification_id_is_noop():
    backend = FakeBackend()
    undone = []
    notifier = Notifier(backend=backend, undo_fn=lambda bid: undone.append(bid))
    notifier.notify_result(_optimized(Path("/tmp/photo.jpg"), 1000, 400))

    backend.on_action(9999, "undo")  # never issued
    assert undone == []


def test_non_undo_action_key_is_noop():
    backend = FakeBackend()
    undone = []
    notifier = Notifier(backend=backend, undo_fn=lambda bid: undone.append(bid))
    notifier.notify_result(_optimized(Path("/tmp/photo.jpg"), 1000, 400))
    nid = backend.sent[0][0]

    backend.on_action(nid, "default")
    assert undone == []


def test_closed_forgets_id_so_later_undo_is_noop():
    backend = FakeBackend()
    undone = []
    notifier = Notifier(backend=backend, undo_fn=lambda bid: undone.append(bid))
    notifier.notify_result(_optimized(Path("/tmp/photo.jpg"), 1000, 400))
    nid = backend.sent[0][0]

    backend.on_closed(nid)
    backend.on_action(nid, "undo")
    assert undone == []


def test_unchanged_and_skipped_send_nothing():
    backend = FakeBackend()
    notifier = Notifier(backend=backend, undo_fn=lambda bid: None)
    notifier.notify_result(JobResult(JobStatus.UNCHANGED, Path("/tmp/a.png"), 100, 100))
    notifier.notify_result(JobResult(JobStatus.SKIPPED, Path("/tmp/b.png"), 100, 100))
    assert backend.sent == []


def test_error_sends_warning_without_action():
    backend = FakeBackend()
    notifier = Notifier(backend=backend, undo_fn=lambda bid: None)
    notifier.notify_result(
        JobResult(JobStatus.ERROR, Path("/tmp/a.png"), 0, 0, message="disk full")
    )
    assert len(backend.sent) == 1
    _, summary, body, actions, _ = backend.sent[0]
    assert actions == []
    assert "a.png" in summary
    assert "disk full" in body


def test_real_dbus_backend_send_does_not_raise_with_no_daemon_on_bus(qapp):
    # Headless test env: there is no notifications daemon on the session bus.
    # send() must degrade gracefully (return an int, never raise) instead of
    # propagating a TypeError/other exception from the D-Bus call.
    backend = DBusNotificationBackend(app_name="Clop-KDE-Test")

    nid = backend.send("photo.jpg", "60% smaller", [("undo", "Undo")], "")
    assert isinstance(nid, int)


def test_real_dbus_backend_send_with_empty_actions_does_not_raise(qapp):
    backend = DBusNotificationBackend(app_name="Clop-KDE-Test")

    nid = backend.send("a.png", "Optimization failed: disk full", [], "")
    assert isinstance(nid, int)
