from klop import service


def test_unit_runs_daemon_headless_in_graphical_session():
    text = service.unit_text("/opt/bin/klop")
    assert 'ExecStart="/opt/bin/klop" daemon --no-tray' in text
    assert "WantedBy=graphical-session.target" in text
    assert "PartOf=graphical-session.target" in text


def test_install_writes_unit_enables_and_drops_autostart(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    legacy = tmp_path / "autostart" / "klop-daemon.desktop"
    legacy.parent.mkdir()
    legacy.write_text("[Desktop Entry]\n")
    calls = []

    dest = service.install_service(
        exec_path="/opt/bin/klop", run=lambda cmd, **kw: calls.append(cmd)
    )

    assert dest == tmp_path / "systemd" / "user" / "klop-daemon.service"
    assert "daemon --no-tray" in dest.read_text()
    assert not legacy.exists()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "klop-daemon.service"],
        ["systemctl", "--user", "restart", "klop-daemon.service"],
    ]
