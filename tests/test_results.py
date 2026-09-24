from pathlib import Path

from klop.job import JobResult, JobStatus
from klop.results import ResultRouter


class FakeTray:
    def __init__(self):
        self.saved = []

    def record_saved(self, n):
        self.saved.append(n)


class FakeOverlay:
    def __init__(self):
        self.shown = []
        self.pending = []
        self.dismissed = 0

    def show_result(self, result):
        self.shown.append(result)

    def show_pending(self, title, thumbnail_source=None):
        self.pending.append((title, thumbnail_source))

    def dismiss(self):
        self.dismissed += 1


class FakeNotifier:
    def __init__(self):
        self.results = []

    def notify_result(self, result):
        self.results.append(result)


def _optimized():
    return JobResult(JobStatus.OPTIMIZED, Path("/tmp/a.png"), 1000, 400, backup_id="b1")


def test_optimized_routes_to_overlay_and_total_not_notifier():
    tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
    ResultRouter(tray, overlay, notifier).on_job_done(_optimized())
    assert tray.saved == [600]
    assert len(overlay.shown) == 1
    assert notifier.results == []
    assert overlay.dismissed == 0


def test_on_job_started_shows_pending(tmp_path):
    tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
    p = tmp_path / "photo.png"
    ResultRouter(tray, overlay, notifier).on_job_started(p)
    assert overlay.pending == [("photo.png", p)]


def test_error_notifies_and_dismisses_pending():
    tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
    result = JobResult(JobStatus.ERROR, Path("/tmp/a.png"), 0, 0, message="disk full")
    ResultRouter(tray, overlay, notifier).on_job_done(result)
    assert notifier.results == [result]
    assert overlay.shown == []  # no result card
    assert overlay.dismissed == 1  # pending card cleared


def test_unchanged_and_skipped_dismiss_pending_silently():
    for status in (JobStatus.UNCHANGED, JobStatus.SKIPPED):
        tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
        ResultRouter(tray, overlay, notifier).on_job_done(
            JobResult(status, Path("/tmp/a.png"), 100, 100)
        )
        assert tray.saved == [] and overlay.shown == [] and notifier.results == []
        assert overlay.dismissed == 1  # pending card cleared, nothing else


class FakeHistory:
    def __init__(self):
        self.records = []

    def record(self, kind, name, path, original_size, new_size, backup_id=None):
        self.records.append((kind, name, path, original_size, new_size, backup_id))


def test_optimized_records_file_history():
    tray, overlay, notifier, history = FakeTray(), FakeOverlay(), FakeNotifier(), FakeHistory()
    ResultRouter(tray, overlay, notifier, history=history).on_job_done(_optimized())
    assert history.records == [("file", "a.png", "/tmp/a.png", 1000, 400, "b1")]


def test_non_optimized_does_not_record():
    tray, overlay, notifier, history = FakeTray(), FakeOverlay(), FakeNotifier(), FakeHistory()
    router = ResultRouter(tray, overlay, notifier, history=history)
    router.on_job_done(JobResult(JobStatus.ERROR, Path("/tmp/a.png"), 0, 0, message="x"))
    router.on_job_done(JobResult(JobStatus.SKIPPED, Path("/tmp/a.png"), 10, 10))
    assert history.records == []


def test_optimized_without_history_does_not_crash():
    tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
    ResultRouter(tray, overlay, notifier).on_job_done(_optimized())  # history=None
    assert len(overlay.shown) == 1
