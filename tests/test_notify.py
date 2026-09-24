import subprocess

from klop import notify


def test_send_notification_shells_out_to_gdbus_notify(monkeypatch):
    calls = {}

    def fake_run(argv, capture_output, text, timeout):
        calls["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="(uint32 42,)", stderr="")

    monkeypatch.setattr(notify.subprocess, "run", fake_run)

    nid = notify.send_notification("photo.jpg", "8.6KB → 3.4KB (-60%)", app_name="Klop")

    argv = calls["argv"]
    assert argv[0] == "gdbus" and "call" in argv
    assert "org.freedesktop.Notifications.Notify" in argv
    assert '"photo.jpg"' in argv  # summary as a gvariant string literal
    assert '"8.6KB → 3.4KB (-60%)"' in argv
    assert nid == 42  # parsed from gdbus reply


def test_send_notification_returns_zero_when_gdbus_missing(monkeypatch):
    def raise_missing(*a, **k):
        raise FileNotFoundError("gdbus not found")

    monkeypatch.setattr(notify.subprocess, "run", raise_missing)

    assert notify.send_notification("s", "b") == 0  # must not raise


def test_send_notification_escapes_quotes_in_body(monkeypatch):
    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="(uint32 1,)", stderr="")

    monkeypatch.setattr(notify.subprocess, "run", fake_run)

    notify.send_notification('a"b', 'say "hi"')

    assert r'"say \"hi\""' in calls["argv"]


def test_wait_for_action_returns_clicked_action_key(monkeypatch):
    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="open\n", stderr="")

    monkeypatch.setattr(notify.subprocess, "run", fake_run)

    key = notify.wait_for_action(
        "pic.png", "1KB → 0.5KB", (("copy", "Copy"), ("open", "Open folder")), icon="i"
    )

    argv = calls["argv"]
    assert argv[0] == "notify-send"
    assert "--action=copy=Copy" in argv and "--action=open=Open folder" in argv
    assert argv[-2:] == ["pic.png", "1KB → 0.5KB"]
    assert key == "open"


def test_wait_for_action_returns_none_when_dismissed_or_failing(monkeypatch):
    monkeypatch.setattr(
        notify.subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="", stderr=""),
    )
    assert notify.wait_for_action("s", "b", (("copy", "Copy"),)) is None

    def raise_missing(*a, **k):
        raise FileNotFoundError("notify-send")

    monkeypatch.setattr(notify.subprocess, "run", raise_missing)
    assert notify.wait_for_action("s", "b", (("copy", "Copy"),)) is None
