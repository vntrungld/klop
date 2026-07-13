import shutil

from clop_kde.cli import main


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
