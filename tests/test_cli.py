import json as _json
import shutil
from pathlib import Path

from klop.backup import BackupStore
from klop.cli import main
from klop.config import Config
from klop.engine import Engine
from klop.history import HistoryStore


def test_cli_import_is_qt_free():
    import subprocess
    import sys

    code = (
        "import klop.cli, sys; "
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
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
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

    import klop.cli as cli_mod

    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
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

    import klop.cli as cli_mod

    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)  # interactive terminal
    sent = []
    monkeypatch.setattr(cli_mod, "send_notification", lambda *a, **k: sent.append(1))

    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    main(["optimize", str(f)])

    assert sent == []  # terminal user already sees stdout; no notification


def test_install_dolphin_writes_service_menu(tmp_path, capsys, monkeypatch):
    menus = tmp_path / "kio" / "servicemenus"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(shutil, "which", lambda name: "/opt/bin/klop")

    rc = main(["install", "--dolphin"])
    out = capsys.readouterr().out

    assert rc == 0
    installed = menus / "klop-optimize.desktop"
    assert installed.exists()
    assert 'Exec="/opt/bin/klop" optimize %F' in installed.read_text()
    assert str(installed) in out


def test_undo_restores(tmp_path, capsys, monkeypatch):
    from klop.backup import BackupStore

    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
    f = tmp_path / "a.png"
    f.write_bytes(b"ORIGINAL")
    store = BackupStore(tmp_path / "backups")
    bid = store.backup(f)
    f.write_bytes(b"CHANGED")

    rc = main(["undo", bid])
    assert rc == 0
    assert f.read_bytes() == b"ORIGINAL"


def test_copy_puts_image_on_clipboard(tmp_path, monkeypatch):
    import klop.cli as cli_mod

    f = tmp_path / "a.png"
    f.write_bytes(b"PNG")
    seen = {}
    monkeypatch.setattr(
        cli_mod.webfetch,
        "copy_image_to_clipboard",
        lambda path: seen.setdefault("path", Path(path)) or True,
    )
    rc = main(["copy", str(f)])
    assert rc == 0
    assert seen["path"] == f


def test_copy_reports_failure_when_clipboard_unavailable(tmp_path, monkeypatch, capsys):
    import klop.cli as cli_mod

    f = tmp_path / "a.png"
    f.write_bytes(b"PNG")
    monkeypatch.setattr(cli_mod.webfetch, "copy_image_to_clipboard", lambda path: False)
    rc = main(["copy", str(f)])
    assert rc == 1
    assert "clipboard" in capsys.readouterr().err.lower()


def test_optimize_reports_optimized(tmp_path, capsys, monkeypatch, sample_png):
    # Force the OPTIMIZED branch deterministically instead of relying on
    # pngquant's actual behavior (on this machine pngquant reports the
    # sample PNG as UNCHANGED, which left this branch uncovered). Inject a
    # fake engine with a fake runner that always writes a smaller file.
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))

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
    monkeypatch.setattr("klop.cli._build_engine", lambda: engine)

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
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))

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
    monkeypatch.setattr("klop.cli._build_engine", lambda: engine)

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
    from klop.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(hist))
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
    # Force an OPTIMIZED result without invoking real tools.
    from klop import cli as cli_mod
    from klop.job import JobResult, JobStatus

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


def test_optimize_convert_uses_result_path_not_deleted_source(tmp_path, capsys, monkeypatch):
    # On a format conversion (e.g. clip.mkv -> clip.mp4) the engine deletes the
    # original source and returns JobResult.path pointing at the new file. The
    # CLI must report and record that new path, not the stale (now-deleted)
    # source path.
    from klop import cli as cli_mod
    from klop.job import JobResult, JobStatus

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(hist))
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))

    src = tmp_path / "clip.mkv"
    src.write_bytes(b"x" * 100)
    converted = tmp_path / "clip.mp4"
    converted.write_bytes(b"x" * 40)
    # The real engine deletes the source as part of the convert; the fake
    # engine below stands in for that, so `src` need not survive here beyond
    # the CLI's initial existence check.

    class _Eng:
        def optimize(self, job):
            return JobResult(JobStatus.OPTIMIZED, converted, 1000, 400, backup_id="B1")

    monkeypatch.setattr(cli_mod, "_build_engine", lambda: _Eng())

    rc = main(["optimize", str(src)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "optimized clip.mp4" in out
    assert "clip.mkv" not in out

    rows = HistoryStore(hist).entries()
    assert len(rows) == 1
    assert rows[0].name == "clip.mp4"
    assert rows[0].path == str(converted)


def test_undo_marks_history_undone(tmp_path, monkeypatch):
    from klop.backup import BackupStore
    from klop.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(hist))
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
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
    from klop.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(hist))
    HistoryStore(hist).record("file", "a.png", "/tmp/a.png", 100, 40, backup_id="b1")
    rc = main(["history", "--json"])
    assert rc == 0
    data = _json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["name"] == "a.png"
    assert data[0]["backup_id"] == "b1"


def test_history_table_lists_names(tmp_path, monkeypatch, capsys):
    from klop.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(hist))
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
    import klop.config as config_mod

    monkeypatch.setattr(config_mod, "default_config_path", lambda: cfg)

    rc = main(["config", "set", "png_lossy=false", "jpeg_max_quality=70"])
    out = capsys.readouterr().out
    assert rc == 0
    printed = _json.loads(out)
    assert printed["png_lossy"] is False and printed["jpeg_max_quality"] == 70
    # persisted so a fresh load sees it
    from klop.config import load_config

    reloaded = load_config(cfg)
    assert reloaded.png_lossy is False and reloaded.jpeg_max_quality == 70


def test_config_set_unknown_key_errors_and_leaves_file(tmp_path, capsys, monkeypatch):
    cfg = tmp_path / "config.toml"
    import klop.config as config_mod

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


def test_optimize_url_downloads_optimizes_records_and_prints_path(
    tmp_path, capsys, monkeypatch, sample_png
):
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
    dest = tmp_path / "webdrop"
    dest.mkdir()

    import klop.cli as cli_mod
    from klop.config import Config
    from klop.job import JobResult, JobStatus

    # cli.py binds `load_config` by name, so patch it on the cli module.
    monkeypatch.setattr(cli_mod, "load_config", lambda path=None: Config(web_drop_dir=str(dest)))

    saved = dest / "pic.png"

    def fake_download(url, *, dest_dir, **kw):
        saved.write_bytes(sample_png.read_bytes())
        return saved

    monkeypatch.setattr(cli_mod.webfetch, "download_image", fake_download)
    monkeypatch.setattr(cli_mod.webfetch, "copy_image_to_clipboard", lambda p: True)

    class _Eng:
        def optimize(self, job):
            return JobResult(JobStatus.OPTIMIZED, job.source_path, 1000, 400, backup_id="B1")

    monkeypatch.setattr(cli_mod, "_build_engine", lambda: _Eng())
    monkeypatch.setattr(cli_mod.sys.stdout, "isatty", lambda: True)  # suppress notification

    rc = main(["optimize-url", "https://ex.com/pic.png"])
    out = capsys.readouterr().out
    assert rc == 0
    assert str(saved) in out  # prints the saved path

    from klop.history import HistoryStore

    entries = HistoryStore().entries()
    assert len(entries) == 1 and entries[0].backup_id == "B1"


def test_optimize_url_convert_uses_result_path_not_deleted_source(
    tmp_path, capsys, monkeypatch, sample_png
):
    # On a convert (here .webp -> .mp4 stand-in: any optimizer with an
    # output_ext) the engine deletes the downloaded original and returns
    # JobResult.path pointing at the new file. The clipboard copy, history
    # record, "saved" message, and notification must all reference that new
    # path, not the deleted download.
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
    dest = tmp_path / "webdrop"
    dest.mkdir()

    import klop.cli as cli_mod
    from klop.config import Config
    from klop.job import JobResult, JobStatus

    monkeypatch.setattr(cli_mod, "load_config", lambda path=None: Config(web_drop_dir=str(dest)))

    downloaded = dest / "pic.gif"
    converted = dest / "pic.mp4"

    def fake_download(url, *, dest_dir, **kw):
        downloaded.write_bytes(sample_png.read_bytes())
        return downloaded

    monkeypatch.setattr(cli_mod.webfetch, "download_image", fake_download)

    clipboard_calls = []
    monkeypatch.setattr(
        cli_mod.webfetch,
        "copy_image_to_clipboard",
        lambda p: clipboard_calls.append(Path(p)) or True,
    )

    class _Eng:
        def optimize(self, job):
            converted.write_bytes(sample_png.read_bytes())
            downloaded.unlink()  # engine deletes the original on convert
            return JobResult(JobStatus.OPTIMIZED, converted, 1000, 400, backup_id="B1")

    monkeypatch.setattr(cli_mod, "_build_engine", lambda: _Eng())
    monkeypatch.setattr(cli_mod.sys.stdout, "isatty", lambda: True)  # suppress notification

    rc = main(["optimize-url", "https://ex.com/pic.gif"])
    out = capsys.readouterr().out
    assert rc == 0

    # Clipboard copy must target the converted file, not the deleted original.
    assert clipboard_calls == [converted]

    # Printed output references the new path/name only.
    assert "optimized pic.mp4" in out
    assert str(converted) in out
    assert "pic.gif" not in out

    entries = HistoryStore().entries()
    assert len(entries) == 1
    assert entries[0].name == "pic.mp4"
    assert entries[0].path == str(converted)
    assert entries[0].backup_id == "B1"


def test_optimize_url_bad_url_exits_1(capsys, monkeypatch):
    import klop.cli as cli_mod

    def boom(url, *, dest_dir, **kw):
        raise ValueError("unsupported URL scheme: ftp")

    monkeypatch.setattr(cli_mod.webfetch, "download_image", boom)
    monkeypatch.setattr(cli_mod.sys.stdout, "isatty", lambda: True)
    rc = main(["optimize-url", "ftp://ex.com/x"])
    assert rc == 1
    assert "scheme" in capsys.readouterr().err


def test_optimize_url_falls_back_to_next_candidate(tmp_path, capsys, monkeypatch, sample_png):
    # A browser drag of a linked image (e.g. Facebook) carries the link's page
    # URL plus the <img src>; the page is HTML ("not an image"), so the CLI
    # must try the other candidates in order.
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
    dest = tmp_path / "webdrop"
    dest.mkdir()

    import klop.cli as cli_mod
    from klop.config import Config
    from klop.job import JobResult, JobStatus

    monkeypatch.setattr(cli_mod, "load_config", lambda path=None: Config(web_drop_dir=str(dest)))

    saved = dest / "pic.png"
    tried = []

    def fake_download(url, *, dest_dir, **kw):
        tried.append(url)
        if "facebook.com/photo" in url:
            raise ValueError("not an image")
        saved.write_bytes(sample_png.read_bytes())
        return saved

    monkeypatch.setattr(cli_mod.webfetch, "download_image", fake_download)
    monkeypatch.setattr(cli_mod.webfetch, "copy_image_to_clipboard", lambda p: True)

    class _Eng:
        def optimize(self, job):
            return JobResult(JobStatus.SKIPPED, job.source_path, 10, 10, message="no gain")

    monkeypatch.setattr(cli_mod, "_build_engine", lambda: _Eng())
    monkeypatch.setattr(cli_mod.sys.stdout, "isatty", lambda: True)

    rc = main([
        "optimize-url",
        "https://www.facebook.com/photo/?fbid=1",
        "https://scontent.xx.fbcdn.net/v/t39/pic.jpg?oh=a&oe=b",
    ])
    assert rc == 0
    assert tried == [
        "https://www.facebook.com/photo/?fbid=1",
        "https://scontent.xx.fbcdn.net/v/t39/pic.jpg?oh=a&oe=b",
    ]
    assert str(saved) in capsys.readouterr().out


def test_optimize_url_reports_error_when_all_candidates_fail(tmp_path, capsys, monkeypatch):
    import klop.cli as cli_mod
    from klop.config import Config

    monkeypatch.setattr(cli_mod, "load_config", lambda path=None: Config(web_drop_dir=str(tmp_path)))

    def fake_download(url, *, dest_dir, **kw):
        raise ValueError("not an image")

    monkeypatch.setattr(cli_mod.webfetch, "download_image", fake_download)
    monkeypatch.setattr(cli_mod.sys.stdout, "isatty", lambda: True)

    rc = main(["optimize-url", "https://a.example/x", "https://b.example/y"])
    assert rc == 1
    assert "not an image" in capsys.readouterr().err


def test_optimize_url_notification_is_detached_with_path(tmp_path, monkeypatch, sample_png):
    # The notification's Copy / Open folder buttons need a process that outlives
    # the CLI, so optimize-url hands the notification to a detached child.
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    import klop.cli as cli_mod
    from klop.config import Config
    from klop.job import JobResult, JobStatus

    monkeypatch.setattr(cli_mod, "load_config", lambda path=None: Config(web_drop_dir=str(tmp_path)))
    saved = tmp_path / "pic.png"
    saved.write_bytes(sample_png.read_bytes())
    monkeypatch.setattr(cli_mod.webfetch, "download_image", lambda url, *, dest_dir, **kw: saved)
    monkeypatch.setattr(cli_mod.webfetch, "copy_image_to_clipboard", lambda p: True)

    class _Eng:
        def optimize(self, job):
            return JobResult(JobStatus.SKIPPED, job.source_path, 10, 10, message="no gain")

    monkeypatch.setattr(cli_mod, "_build_engine", lambda: _Eng())
    monkeypatch.setattr(cli_mod.sys.stdout, "isatty", lambda: False)
    spawned = []
    monkeypatch.setattr(
        cli_mod.subprocess, "Popen", lambda argv, **kw: spawned.append((argv, kw))
    )

    assert main(["optimize-url", "https://ex.com/pic.png"]) == 0

    (argv, kw), = spawned
    assert argv[:4] == [cli_mod.sys.executable, "-m", "klop.cli", "notify-saved"]
    assert argv[4] == str(saved)
    assert kw["start_new_session"] is True
    assert kw["stdout"] == cli_mod.subprocess.DEVNULL  # don't hold the plasmoid's pipe


def test_notify_saved_copy_action_copies_image(tmp_path, monkeypatch):
    import klop.cli as cli_mod

    pic = tmp_path / "pic.png"
    pic.write_bytes(b"x")
    copied = []
    monkeypatch.setattr(cli_mod, "wait_for_action", lambda *a, **k: "copy")
    monkeypatch.setattr(cli_mod.webfetch, "copy_image_to_clipboard", lambda p: copied.append(p) or True)

    assert main(["notify-saved", str(pic), "pic.png", "body"]) == 0
    assert copied == [pic]


def test_notify_saved_open_action_selects_file_in_file_manager(tmp_path, monkeypatch):
    import klop.cli as cli_mod

    pic = tmp_path / "pic.png"
    pic.write_bytes(b"x")
    runs = []
    monkeypatch.setattr(cli_mod, "wait_for_action", lambda *a, **k: "open")
    monkeypatch.setattr(cli_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli_mod.subprocess, "Popen", lambda argv, **kw: runs.append(argv))

    assert main(["notify-saved", str(pic), "pic.png", "body"]) == 0
    assert runs == [["/usr/bin/dolphin", "--select", str(pic)]]


def test_install_without_flags_runs_every_component(monkeypatch):
    import klop.cli as cli

    ran = []
    monkeypatch.setattr(cli, "_cmd_install_plasmoid", lambda a: ran.append("plasmoid") or 0)
    monkeypatch.setattr(cli, "_cmd_install_dolphin", lambda a: ran.append("dolphin") or 0)
    monkeypatch.setattr(cli, "_cmd_install_service", lambda a: ran.append("service") or 0)

    assert main(["install"]) == 0
    assert ran == ["plasmoid", "dolphin", "service"]


def test_install_flags_select_components(monkeypatch):
    import klop.cli as cli

    ran = []
    monkeypatch.setattr(cli, "_cmd_install_plasmoid", lambda a: ran.append("plasmoid") or 0)
    monkeypatch.setattr(cli, "_cmd_install_dolphin", lambda a: ran.append("dolphin") or 0)
    monkeypatch.setattr(cli, "_cmd_install_service", lambda a: ran.append("service") or 1)

    assert main(["install", "--dolphin", "--service"]) == 1  # a failing step fails the run
    assert ran == ["dolphin", "service"]
