import shutil
from pathlib import Path

import pytest

from clop_kde.backup import BackupStore
from clop_kde.config import Config
from clop_kde.engine import Engine
from clop_kde.job import JobResult, JobStatus, OptimizationJob
from clop_kde.media import MediaType


def make_engine(tmp_path, caps, runner):
    return Engine(
        config=Config(),
        backup_store=BackupStore(tmp_path / "backups"),
        capabilities=caps,
        runner=runner,
    )


def test_skipped_when_no_optimizer(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    def runner(cmd, stdout_path):  # never called
        raise AssertionError("runner should not run when no tool available")

    engine = make_engine(tmp_path, {"pngquant": None}, runner)
    result = engine.optimize(OptimizationJob(source_path=f))
    assert result.status == JobStatus.SKIPPED
    assert f.read_bytes().startswith(b"\x89PNG")  # untouched


def test_optimized_replaces_and_backs_up(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000)

    def runner(cmd, stdout_path):
        # Simulate a tool writing a smaller file to the temp output.
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        return 0

    engine = make_engine(tmp_path, {"pngquant": "/usr/bin/pngquant"}, runner)
    result = engine.optimize(OptimizationJob(source_path=f))
    assert result.status == JobStatus.OPTIMIZED
    assert result.saved_bytes > 0
    assert len(f.read_bytes()) == 108  # replaced with smaller output
    assert result.backup_id is not None

    restored = engine.undo(result.backup_id)
    assert restored == f
    assert len(f.read_bytes()) == 1008  # original restored


def test_unchanged_when_not_smaller(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    def runner(cmd, stdout_path):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)  # same size
        return 0

    engine = make_engine(tmp_path, {"pngquant": "/usr/bin/pngquant"}, runner)
    result = engine.optimize(OptimizationJob(source_path=f))
    assert result.status == JobStatus.UNCHANGED
    assert result.backup_id is None


def test_unchanged_when_runner_fails(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    def runner(cmd, stdout_path):
        return 99  # pngquant "quality not met" style failure, no output written

    engine = make_engine(tmp_path, {"pngquant": "/usr/bin/pngquant"}, runner)
    result = engine.optimize(OptimizationJob(source_path=f))
    assert result.status == JobStatus.UNCHANGED
    assert result.backup_id is None


@pytest.mark.skipif(not shutil.which("pngquant"), reason="pngquant not installed")
def test_real_pngquant_end_to_end(tmp_path, sample_png):
    target = tmp_path / "real.png"
    target.write_bytes(sample_png.read_bytes())
    original_size = target.stat().st_size

    engine = Engine(
        config=Config(),
        backup_store=BackupStore(tmp_path / "backups"),
        capabilities={"pngquant": shutil.which("pngquant")},
    )
    result = engine.optimize(OptimizationJob(source_path=target))
    assert result.status in (JobStatus.OPTIMIZED, JobStatus.UNCHANGED)
    if result.status == JobStatus.OPTIMIZED:
        assert target.stat().st_size < original_size
        engine.undo(result.backup_id)
        assert target.stat().st_size == original_size
