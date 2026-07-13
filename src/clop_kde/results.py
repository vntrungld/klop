from __future__ import annotations

from .job import JobResult, JobStatus


class ResultRouter:
    """Routes optimization results across the tray total, floating overlay, and notifier.

    File/drop results (OPTIMIZED) surface as the floating overlay; errors notify;
    unchanged/skipped are silent. Clipboard results are routed separately by the daemon."""

    def __init__(self, tray, overlay, notifier):
        self._tray = tray
        self._overlay = overlay
        self._notifier = notifier

    def on_job_done(self, result: JobResult) -> None:
        if result.status == JobStatus.OPTIMIZED:
            self._tray.record_saved(result.saved_bytes)
            self._overlay.show_result(result)
        elif result.status == JobStatus.ERROR:
            self._notifier.notify_result(result)
        # UNCHANGED / SKIPPED: intentionally silent
