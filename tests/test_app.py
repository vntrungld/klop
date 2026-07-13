from pathlib import Path

from PySide6.QtCore import QObject, Signal

from clop_kde import app as app_module
from clop_kde.app import TrayApp, load_tray_icon
from clop_kde.job import JobResult, JobStatus


class FakeQueue(QObject):
    job_done = Signal(object)

    def __init__(self):
        super().__init__()
        self.submitted = []

    def submit(self, paths):
        self.submitted.append(list(paths))


class FakeNotifier:
    def __init__(self):
        self.results = []

    def notify_result(self, result):
        self.results.append(result)


def test_optimize_action_submits_picked_files(qapp):
    queue = FakeQueue()
    notifier = FakeNotifier()
    picked = [Path("/tmp/a.png"), Path("/tmp/b.png")]
    tray = TrayApp(queue=queue, notifier=notifier, pick_files=lambda: picked)

    tray.optimize_action.trigger()

    assert queue.submitted == [picked]


def test_disabling_greys_out_the_picker_and_blocks_submit(qapp):
    queue = FakeQueue()
    tray = TrayApp(queue=queue, notifier=FakeNotifier(), pick_files=lambda: [Path("/tmp/a.png")])

    tray.enabled_action.setChecked(False)  # fires toggled(False)

    assert tray.optimize_action.isEnabled() is False
    tray.optimize_action.trigger()  # disabled QAction: triggered is not emitted
    assert queue.submitted == []


def test_job_done_updates_saved_total_and_forwards_to_notifier(qapp):
    queue = FakeQueue()
    notifier = FakeNotifier()
    tray = TrayApp(queue=queue, notifier=notifier, pick_files=lambda: [])

    result = JobResult(JobStatus.OPTIMIZED, Path("/tmp/a.png"), 10000, 5000, backup_id="b1")
    queue.job_done.emit(result)

    assert tray.saved_total() == 5000
    assert "Saved:" in tray.saved_action.text()
    assert "4.9KB" in tray.saved_action.text()  # 5000 bytes -> 4.9KB
    assert notifier.results == [result]


def test_non_optimized_job_done_does_not_change_total_but_still_notifies(qapp):
    queue = FakeQueue()
    notifier = FakeNotifier()
    tray = TrayApp(queue=queue, notifier=notifier, pick_files=lambda: [])

    result = JobResult(JobStatus.SKIPPED, Path("/tmp/a.png"), 100, 100)
    queue.job_done.emit(result)

    assert tray.saved_total() == 0
    assert notifier.results == [result]


def test_load_tray_icon_returns_a_non_null_icon(qapp):
    icon = load_tray_icon()
    assert not icon.isNull()


def test_open_config_does_not_raise_when_xdg_open_is_missing(qapp, monkeypatch, tmp_path):
    queue = FakeQueue()
    tray = TrayApp(queue=queue, notifier=FakeNotifier(), pick_files=lambda: [])
    monkeypatch.setattr(app_module, "default_config_path", lambda: tmp_path / "clop-kde.toml")

    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("xdg-open not found")

    monkeypatch.setattr(app_module.subprocess, "Popen", raise_missing)

    tray._on_open_config()  # must not raise
