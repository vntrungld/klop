import os
import shutil
import stat
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


@pytest.mark.skipif(not shutil.which("jpegoptim"), reason="jpegoptim not installed")
def test_real_jpegoptim_end_to_end(tmp_path, sample_jpeg):
    target = tmp_path / "real.jpg"
    target.write_bytes(sample_jpeg.read_bytes())
    original_size = target.stat().st_size

    engine = Engine(
        config=Config(),
        backup_store=BackupStore(tmp_path / "backups"),
        capabilities={"jpegoptim": shutil.which("jpegoptim")},
    )
    result = engine.optimize(OptimizationJob(source_path=target))
    assert result.status in (JobStatus.OPTIMIZED, JobStatus.UNCHANGED)
    if result.status == JobStatus.OPTIMIZED:
        assert target.stat().st_size < original_size
        engine.undo(result.backup_id)
        assert target.stat().st_size == original_size


def test_use_stdout_wiring_passes_temp_path(tmp_path, sample_jpeg):
    target = tmp_path / "real.jpg"
    target.write_bytes(sample_jpeg.read_bytes())

    recorded = {}

    def runner(cmd, stdout_path):
        recorded["stdout_path"] = stdout_path
        if stdout_path is not None:
            stdout_path.write_bytes(b"\xff\xd8\xff" + b"x" * 10)
        return 0

    engine = make_engine(tmp_path, {"jpegoptim": "/usr/bin/jpegoptim"}, runner)
    engine.optimize(OptimizationJob(source_path=target))

    assert recorded["stdout_path"] is not None
    assert recorded["stdout_path"].parent == target.parent


def test_use_stdout_false_passes_none(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000)

    recorded = {}

    def runner(cmd, stdout_path):
        recorded["stdout_path"] = stdout_path
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        return 0

    engine = make_engine(tmp_path, {"pngquant": "/usr/bin/pngquant"}, runner)
    engine.optimize(OptimizationJob(source_path=f))

    assert recorded["stdout_path"] is None


def test_optimize_preserves_source_permissions(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000)
    os.chmod(f, 0o644)

    def runner(cmd, stdout_path):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        return 0

    engine = make_engine(tmp_path, {"pngquant": "/usr/bin/pngquant"}, runner)
    result = engine.optimize(OptimizationJob(source_path=f))
    assert result.status == JobStatus.OPTIMIZED
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o644


def test_convert_writes_new_extension_and_drops_source(tmp_path):
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"\x1a\x45\xdf\xa3" + b"x" * 5000)  # EBML magic → VIDEO

    def runner(cmd, stdout_path):
        out = Path(cmd[-1])                    # ffmpeg output is the last arg
        assert out.suffix == ".mp4"
        out.write_bytes(b"\x00" * 500)
        return 0

    engine = make_engine(tmp_path, {"ffmpeg": "/usr/bin/ffmpeg"}, runner)
    result = engine.optimize(OptimizationJob(source_path=src))

    assert result.status == JobStatus.OPTIMIZED
    dest = tmp_path / "clip.mp4"
    assert result.path == dest
    assert dest.exists()
    assert not src.exists()                    # original converted away
    assert result.backup_id is not None

    # Undo restores the original .mkv at its original path.
    restored = engine.undo(result.backup_id)
    assert restored == src
    assert src.exists()
    assert len(src.read_bytes()) == 5004


def test_convert_dedups_when_dest_exists(tmp_path):
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"\x1a\x45\xdf\xa3" + b"x" * 5000)
    taken = tmp_path / "clip.mp4"
    taken.write_bytes(b"unrelated")            # pre-existing, must not be clobbered

    def runner(cmd, stdout_path):
        Path(cmd[-1]).write_bytes(b"\x00" * 500)
        return 0

    engine = make_engine(tmp_path, {"ffmpeg": "/usr/bin/ffmpeg"}, runner)
    result = engine.optimize(OptimizationJob(source_path=src))

    assert result.status == JobStatus.OPTIMIZED
    assert result.path == tmp_path / "clip-1.mp4"
    assert taken.read_bytes() == b"unrelated"  # untouched


def test_convert_unchanged_when_not_smaller_keeps_source(tmp_path):
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"\x1a\x45\xdf\xa3" + b"x" * 100)

    def runner(cmd, stdout_path):
        Path(cmd[-1]).write_bytes(b"\x00" * 5000)   # bigger than original
        return 0

    engine = make_engine(tmp_path, {"ffmpeg": "/usr/bin/ffmpeg"}, runner)
    result = engine.optimize(OptimizationJob(source_path=src))

    assert result.status == JobStatus.UNCHANGED
    assert src.exists()                        # original kept
    assert not (tmp_path / "clip.mp4").exists()  # no converted file left behind
    assert result.backup_id is None


def test_optimize_returns_error_on_replace_failure(tmp_path, monkeypatch):
    f = tmp_path / "a.png"
    original_bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 1000
    f.write_bytes(original_bytes)

    def runner(cmd, stdout_path):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        return 0

    engine = make_engine(tmp_path, {"pngquant": "/usr/bin/pngquant"}, runner)

    def failing_replace(_src, _dst):
        raise OSError("simulated ENOSPC")

    monkeypatch.setattr(os, "replace", failing_replace)

    result = engine.optimize(OptimizationJob(source_path=f))
    assert result.status == JobStatus.ERROR
    assert "simulated ENOSPC" in result.message
    assert f.read_bytes() == original_bytes


def test_convert_undo_removes_the_converted_file(tmp_path):
    # Undoing a convert must leave the directory as it was: original back,
    # converted file gone (not orphaned alongside it).
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"\x1a\x45\xdf\xa3" + b"x" * 5000)

    def runner(cmd, stdout_path):
        Path(cmd[-1]).write_bytes(b"\x00" * 500)
        return 0

    engine = make_engine(tmp_path, {"ffmpeg": "/usr/bin/ffmpeg"}, runner)
    result = engine.optimize(OptimizationJob(source_path=src))
    dest = tmp_path / "clip.mp4"
    assert result.status == JobStatus.OPTIMIZED and dest.exists()

    engine.undo(result.backup_id)
    assert src.exists()
    assert not dest.exists()


def test_convert_undo_keeps_converted_file_the_user_changed(tmp_path):
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"\x1a\x45\xdf\xa3" + b"x" * 5000)

    def runner(cmd, stdout_path):
        Path(cmd[-1]).write_bytes(b"\x00" * 500)
        return 0

    engine = make_engine(tmp_path, {"ffmpeg": "/usr/bin/ffmpeg"}, runner)
    result = engine.optimize(OptimizationJob(source_path=src))
    dest = tmp_path / "clip.mp4"
    dest.write_bytes(b"the user re-edited this clip")  # different size

    engine.undo(result.backup_id)
    assert src.exists()
    assert dest.read_bytes() == b"the user re-edited this clip"


def test_same_extension_undo_does_not_delete_anything(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000)

    def runner(cmd, stdout_path):
        Path(cmd[cmd.index("--output") + 1]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        return 0

    engine = make_engine(tmp_path, {"pngquant": "/usr/bin/pngquant"}, runner)
    result = engine.optimize(OptimizationJob(source_path=f))
    engine.undo(result.backup_id)
    assert f.exists() and len(f.read_bytes()) == 1008
