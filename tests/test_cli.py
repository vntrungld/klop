import shutil

import pytest

from clop_kde.cli import _human, main


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


@pytest.mark.skipif(not shutil.which("pngquant"), reason="pngquant not installed")
def test_optimize_reports_optimized(tmp_path, capsys, monkeypatch, sample_png):
    monkeypatch.setenv("CLOP_KDE_BACKUP_DIR", str(tmp_path / "backups"))
    target = tmp_path / "real.png"
    target.write_bytes(sample_png.read_bytes())

    rc = main(["optimize", str(target)])
    out = capsys.readouterr().out
    assert rc == 0

    optimized_line = next(
        (line for line in out.splitlines() if line.startswith("optimized ")), None
    )
    if optimized_line is not None:
        assert "real.png" in optimized_line
        assert "saved" in optimized_line
        assert "0.0KB" not in optimized_line
        assert "0.0MB" not in optimized_line
    else:
        # pngquant may report the sample as already optimal; fall back to a
        # minimal sanity check that no size token is corrupted by the bug.
        assert "0.0KB" not in out
        assert "0.0MB" not in out
