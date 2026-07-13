from pathlib import Path

from clop_kde.job import JobResult, JobStatus, OptimizationJob
from clop_kde.queue import OptimizationQueue


def test_submit_runs_each_path_and_emits_results(qapp, tmp_path):
    seen = []

    def fake_optimize(job: OptimizationJob) -> JobResult:
        seen.append(job.source_path)
        return JobResult(JobStatus.OPTIMIZED, job.source_path, 1000, 400, backup_id="b1")

    q = OptimizationQueue(optimize_fn=fake_optimize, concurrency=2)
    results = []
    q.job_done.connect(results.append)

    q.submit([tmp_path / "a.png", tmp_path / "b.png"])
    q.wait_for_done(5000)
    qapp.processEvents()

    assert len(results) == 2
    assert {r.status for r in results} == {JobStatus.OPTIMIZED}
    assert set(seen) == {tmp_path / "a.png", tmp_path / "b.png"}


def test_worker_exception_becomes_error_result(qapp, tmp_path):
    def boom(job: OptimizationJob) -> JobResult:
        raise RuntimeError("kaboom")

    q = OptimizationQueue(optimize_fn=boom, concurrency=1)
    results = []
    q.job_done.connect(results.append)

    q.submit([tmp_path / "x.png"])
    q.wait_for_done(5000)
    qapp.processEvents()

    assert len(results) == 1
    assert results[0].status == JobStatus.ERROR
    assert "kaboom" in results[0].message
    assert results[0].path == tmp_path / "x.png"


def test_job_started_is_emitted_before_job_done(qapp, tmp_path):
    def fake_optimize(job):
        return JobResult(JobStatus.OPTIMIZED, job.source_path, 1000, 400, backup_id="b1")

    q = OptimizationQueue(optimize_fn=fake_optimize, concurrency=1)
    events = []
    q.job_started.connect(lambda path: events.append(("start", path)))
    q.job_done.connect(lambda result: events.append(("done", result.status)))

    p = tmp_path / "a.png"
    q.submit([p])
    q.wait_for_done(5000)
    qapp.processEvents()

    assert len(events) == 2
    assert events[0] == ("start", p)  # started fires first, with the path
    assert events[1][0] == "done"
