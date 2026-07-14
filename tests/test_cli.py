import json as _json
import shutil
from pathlib import Path

import pytest

from clop_kde.backup import BackupStore
from clop_kde.cli import main
from clop_kde.config import Config
from clop_kde.engine import Engine
from clop_kde.history import HistoryStore


def test_cli_import_is_qt_free():
    import subprocess
    import sys

    code = (
        "import clop_kde.cli, sys; "
        "assert 'PySide6' not in sys.modules, "
        "sorted(m for m in sys.modules if 'PySide' in m)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


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


def test_optimize_notifies_when_launched_without_a_terminal(tmp_path, monkeypatch):
    # Dolphin runs the service menu with no controlling terminal, so stdout is
    # swallowed; the CLI must surface a desktop notification instead.
    import sys

    import clop_kde.cli as cli_mod

    monkeypatch.setenv("CLOP_KDE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(shutil, "which", lambda name: None)  # no tools -> skipped
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)  # not a terminal
    sent = []
    monkeypatch.setattr(
        cli_mod, "send_notification", lambda summary, body, **kw: sent.append((summary, body))
    )

    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    rc = main(["optimize", str(f)])

    assert rc == 0
    assert len(sent) == 1  # exactly one summary notification


def test_optimize_does_not_notify_in_a_terminal(tmp_path, monkeypatch):
    import sys

    import clop_kde.cli as cli_mod

    monkeypatch.setenv("CLOP_KDE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)  # interactive terminal
    sent = []
    monkeypatch.setattr(
        cli_mod, "send_notification", lambda *a, **k: sent.append(1)
    )

    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    main(["optimize", str(f)])

    assert sent == []  # terminal user already sees stdout; no notification


def test_install_dolphin_writes_service_menu(tmp_path, capsys, monkeypatch):
    menus = tmp_path / "kio" / "servicemenus"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(shutil, "which", lambda name: "/opt/bin/clop-kde")

    rc = main(["install-dolphin"])
    out = capsys.readouterr().out

    assert rc == 0
    installed = menus / "clop-kde-optimize.desktop"
    assert installed.exists()
    assert 'Exec="/opt/bin/clop-kde" optimize %F' in installed.read_text()
    assert str(installed) in out


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


def test_optimize_records_file_history(tmp_path, monkeypatch):
    from clop_kde.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("CLOP_KDE_HISTORY_FILE", str(hist))
    monkeypatch.setenv("CLOP_KDE_BACKUP_DIR", str(tmp_path / "backups"))
    # Force an OPTIMIZED result without invoking real tools.
    from clop_kde import cli as cli_mod
    from clop_kde.job import JobResult, JobStatus

    f = tmp_path / "a.png"
    f.write_bytes(b"x" * 100)

    class _Eng:
        def optimize(self, job):
            return JobResult(JobStatus.OPTIMIZED, job.source_path, 100, 40, backup_id="bid1")

    monkeypatch.setattr(cli_mod, "_build_engine", lambda: _Eng())
    rc = main(["optimize", str(f)])
    assert rc == 0
    rows = HistoryStore(hist).entries()
    assert len(rows) == 1
    assert rows[0].kind == "file"
    assert rows[0].name == "a.png"
    assert rows[0].backup_id == "bid1"


def test_undo_marks_history_undone(tmp_path, monkeypatch):
    from clop_kde.backup import BackupStore
    from clop_kde.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("CLOP_KDE_HISTORY_FILE", str(hist))
    monkeypatch.setenv("CLOP_KDE_BACKUP_DIR", str(tmp_path / "backups"))
    # Seed a history row and a matching backup.
    store = HistoryStore(hist)
    f = tmp_path / "a.png"
    f.write_bytes(b"ORIGINAL")
    bstore = BackupStore(tmp_path / "backups")
    bid = bstore.backup(f)
    store.record("file", "a.png", str(f), 100, 40, backup_id=bid)
    f.write_bytes(b"CHANGED")

    rc = main(["undo", bid])
    assert rc == 0
    assert HistoryStore(hist).entries()[0].undone is True


def test_history_json_outputs_entries(tmp_path, monkeypatch, capsys):
    from clop_kde.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("CLOP_KDE_HISTORY_FILE", str(hist))
    HistoryStore(hist).record("file", "a.png", "/tmp/a.png", 100, 40, backup_id="b1")
    rc = main(["history", "--json"])
    assert rc == 0
    data = _json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["name"] == "a.png"
    assert data[0]["backup_id"] == "b1"


def test_history_table_lists_names(tmp_path, monkeypatch, capsys):
    from clop_kde.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("CLOP_KDE_HISTORY_FILE", str(hist))
    HistoryStore(hist).record("clipboard", "Clipboard image", None, 500, 200)
    rc = main(["history"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Clipboard image" in out
    assert "clipboard" in out


def test_config_get_json_has_all_fields(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))  # no config file -> defaults
    rc = main(["config", "get", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = _json.loads(out)
    assert data["png_lossy"] is True
    assert data["pngquant_quality"] == [65, 80]


def test_config_set_persists_and_prints_effective(tmp_path, capsys, monkeypatch):
    cfg = tmp_path / "config.toml"
    import clop_kde.config as config_mod
    monkeypatch.setattr(config_mod, "default_config_path", lambda: cfg)

    rc = main(["config", "set", "png_lossy=false", "jpeg_max_quality=70"])
    out = capsys.readouterr().out
    assert rc == 0
    printed = _json.loads(out)
    assert printed["png_lossy"] is False and printed["jpeg_max_quality"] == 70
    # persisted so a fresh load sees it
    from clop_kde.config import load_config
    reloaded = load_config(cfg)
    assert reloaded.png_lossy is False and reloaded.jpeg_max_quality == 70


def test_config_set_unknown_key_errors_and_leaves_file(tmp_path, capsys, monkeypatch):
    cfg = tmp_path / "config.toml"
    import clop_kde.config as config_mod
    monkeypatch.setattr(config_mod, "default_config_path", lambda: cfg)

    rc = main(["config", "set", "bogus=1"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "bogus" in err
    assert not cfg.exists()  # nothing written


def test_config_set_bad_assignment_errors(capsys):
    rc = main(["config", "set", "png_lossy"])  # missing '='
    assert rc == 2
    assert "key=value" in capsys.readouterr().err
