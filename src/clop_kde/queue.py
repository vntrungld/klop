from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .job import JobResult, JobStatus, OptimizationJob


class _JobRunnable(QRunnable):
    def __init__(self, queue: "OptimizationQueue", path: Path):
        super().__init__()
        self._queue = queue
        self._path = path

    def run(self) -> None:
        result = self._queue._run_one(self._path)
        # Emitting from the worker thread is safe; Qt marshals the signal to
        # the receiver's (GUI) thread via a queued connection.
        self._queue.job_done.emit(result)


class OptimizationQueue(QObject):
    """Runs optimization jobs off the GUI thread via a bounded QThreadPool."""

    job_done = Signal(object)  # payload: JobResult

    def __init__(
        self,
        optimize_fn: Callable[[OptimizationJob], JobResult],
        concurrency: int = 2,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._optimize_fn = optimize_fn
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(max(1, concurrency))

    def submit(self, paths: list[Path]) -> None:
        for raw in paths:
            self._pool.start(_JobRunnable(self, Path(raw)))

    def wait_for_done(self, msec: int = -1) -> bool:
        return self._pool.waitForDone(msec)

    def _run_one(self, path: Path) -> JobResult:
        try:
            return self._optimize_fn(OptimizationJob(source_path=path))
        except Exception as exc:  # noqa: BLE001 - surface any worker failure as ERROR
            return JobResult(
                status=JobStatus.ERROR,
                path=path,
                original_size=0,
                new_size=0,
                message=str(exc),
            )
