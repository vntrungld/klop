from __future__ import annotations

from pathlib import Path

from .job import JobResult, JobStatus


class ResultRouter:
    """Routes optimization lifecycle events across the tray total, floating overlay,
    and notifier. A pending overlay card is shown while a file/drop job runs, then
    replaced by the result (OPTIMIZED) or dismissed (error/unchanged/skipped)."""

    def __init__(self, tray, overlay, notifier, history=None):
        self._tray = tray
        self._overlay = overlay
        self._notifier = notifier
        self._history = history

    def on_job_started(self, path) -> None:
        path = Path(path)
        self._overlay.show_pending(path.name, path)

    def on_job_done(self, result: JobResult) -> None:
        if result.status == JobStatus.OPTIMIZED:
            self._tray.record_saved(result.saved_bytes)
            self._overlay.show_result(result)  # replaces the pending card
            if self._history is not None:
                p = Path(result.path)
                self._history.record(
                    "file",
                    p.name,
                    str(p),
                    result.original_size,
                    result.new_size,
                    result.backup_id,
                )
        elif result.status == JobStatus.ERROR:
            self._notifier.notify_result(result)
            self._overlay.dismiss()
        else:  # UNCHANGED / SKIPPED
            self._overlay.dismiss()
