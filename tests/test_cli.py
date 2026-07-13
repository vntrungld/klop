import shutil
from pathlib import Path

import pytest

from clop_kde.backup import BackupStore
from clop_kde.cli import _human, main
from clop_kde.config import Config
from clop_kde.engine import Engine


def test_human_bytes():
    assert _human(500) == "500B"


def test_human_kilobytes():
    assert _human(2048) == "2.0KB"


def test_human_kilobytes_fractional():
    assert _human(1536) == "1.5KB"


def test_human_megabytes():
    assert _human(1048576) == "1.0MB"


def test_human_gigabytes():
    assert _human(3 * 1024**3) == "3.0GB"


def test_caps_lists_tools(capsys, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    rc = main(["caps"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pngquant" in out
    assert "/usr/bin/pngquant" in out


def test_optimize_reports_skipped(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CLOP_KDE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(shutil, "which", lambda name: None)  # no tools
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    rc = main(["optimize", str(f)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "skipped" in out.lower()
    assert "a.png" in out


def test_optimize_missing_file_errors(tmp_path, capsys):
    rc = main(["optimize", str(tmp_path / "ghost.png")])
    assert rc == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_undo_restores(tmp_path, capsys, monkeypatch):
    from clop_kde.backup import BackupStore

    monkeypatch.setenv("CLOP_KDE_BACKUP_DIR", str(tmp_path / "backups"))
    f = tmp_path / "a.png"
    f.write_bytes(b"ORIGINAL")
    store = BackupStore(tmp_path / "backups")
    bid = store.backup(f)
    f.write_bytes(b"CHANGED")

    rc = main(["undo", bid])
    assert rc == 0
    assert f.read_bytes() == b"ORIGINAL"


def test_optimize_reports_optimized(tmp_path, capsys, monkeypatch, sample_png):
    # Force the OPTIMIZED branch deterministically instead of relying on
    # pngquant's actual behavior (on this machine pngquant reports the
    # sample PNG as UNCHANGED, which left this branch uncovered). Inject a
    # fake engine with a fake runner that always writes a smaller file.
    monkeypatch.setenv("CLOP_KDE_BACKUP_DIR", str(tmp_path / "backups"))

    target = tmp_path / "real.png"
    target.write_bytes(sample_png.read_bytes())

    def fake_runner(cmd, stdout_path):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 10)
        return 0

    engine = Engine(
        config=Config(),
        backup_store=BackupStore(tmp_path / "backups"),
        capabilities={"pngquant": "/usr/bin/pngquant"},
        runner=fake_runner,
    )
    monkeypatch.setattr("clop_kde.cli._build_engine", lambda: engine)

    rc = main(["optimize", str(target)])
    out = capsys.readouterr().out
    assert rc == 0

    optimized_line = next(
        (line for line in out.splitlines() if line.startswith("optimized ")), None
    )
    assert optimized_line is not None
    assert "real.png" in optimized_line
    assert "saved" in optimized_line
    assert "KB" in optimized_line
    assert "0.0KB" not in optimized_line
    assert "0.0MB" not in optimized_line


class _SelectivelyFailingBackupStore:
    """backup_store stand-in whose backup() raises OSError for one path only."""

    def __init__(self, real_store, fail_for_name):
        self._real = real_store
        self._fail_for_name = fail_for_name

    def backup(self, path):
        if path.name == self._fail_for_name:
            raise OSError("simulated disk failure")
        return self._real.backup(path)

    def restore(self, backup_id):
        return self._real.restore(backup_id)


def test_optimize_error_result_prints_to_stderr_and_continues(
    tmp_path, capsys, monkeypatch, sample_png
):
    monkeypatch.setenv("CLOP_KDE_BACKUP_DIR", str(tmp_path / "backups"))

    bad = tmp_path / "bad.png"
    bad.write_bytes(sample_png.read_bytes())
    good = tmp_path / "good.png"
    good.write_bytes(sample_png.read_bytes())

    def fake_runner(cmd, stdout_path):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 10)
        return 0

    real_store = BackupStore(tmp_path / "backups")
    engine = Engine(
        config=Config(),
        backup_store=_SelectivelyFailingBackupStore(real_store, "bad.png"),
        capabilities={"pngquant": "/usr/bin/pngquant"},
        runner=fake_runner,
    )
    monkeypatch.setattr("clop_kde.cli._build_engine", lambda: engine)

    rc = main(["optimize", str(bad), str(good)])
    captured = capsys.readouterr()

    assert rc == 1
    assert "error" in captured.err.lower()
    assert "bad.png" in captured.err
    # The batch must continue: the second (good) file is still processed
    # successfully even though the first one errored.
    optimized_line = next(
        (line for line in captured.out.splitlines() if line.startswith("optimized ")),
        None,
    )
    assert optimized_line is not None
    assert "good.png" in optimized_line
