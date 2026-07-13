from pathlib import Path

from clop_kde.job import JobResult, JobStatus
from clop_kde.results import ResultRouter


class FakeTray:
    def __init__(self):
        self.saved = []

    def record_saved(self, n):
        self.saved.append(n)


class FakeOverlay:
    def __init__(self):
        self.shown = []

    def show_result(self, result):
        self.shown.append(result)


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


def test_error_routes_to_notifier_not_overlay():
    tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
    result = JobResult(JobStatus.ERROR, Path("/tmp/a.png"), 0, 0, message="disk full")
    ResultRouter(tray, overlay, notifier).on_job_done(result)
    assert notifier.results == [result]
    assert overlay.shown == []
    assert tray.saved == []


def test_unchanged_and_skipped_are_silent():
    for status in (JobStatus.UNCHANGED, JobStatus.SKIPPED):
        tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
        ResultRouter(tray, overlay, notifier).on_job_done(
            JobResult(status, Path("/tmp/a.png"), 100, 100)
        )
        assert tray.saved == [] and overlay.shown == [] and notifier.results == []
