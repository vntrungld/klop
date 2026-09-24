from klop import plasmoid


def _fake_pkg(root):
    # minimal package tree the installer copies
    (root / "contents" / "ui").mkdir(parents=True)
    (root / "metadata.json").write_text('{"KPlugin": {"Id": "org.trungld.klop"}}')
    (root / "contents" / "ui" / "main.qml").write_text("// main")
    return root


def test_dest_dir_honours_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert plasmoid.plasmoid_dest_dir() == (
        tmp_path / "data" / "plasma" / "plasmoids" / "org.trungld.klop"
    )


def test_install_copies_package_and_bakes_backend_js(tmp_path):
    src = _fake_pkg(tmp_path / "src")
    dest = tmp_path / "out" / "org.trungld.klop"

    result = plasmoid.install_plasmoid(src=src, dest_dir=dest, klop_bin="/opt/bin/klop")

    assert result == dest
    assert (dest / "metadata.json").exists()
    assert (dest / "contents" / "ui" / "main.qml").exists()
    backend = (dest / "contents" / "code" / "backend.js").read_text()
    assert 'var KLOP_BIN = "/opt/bin/klop"' in backend
    assert ".pragma library" in backend


def test_install_replaces_existing_dest(tmp_path):
    src = _fake_pkg(tmp_path / "src")
    dest = tmp_path / "out" / "org.trungld.klop"
    dest.mkdir(parents=True)
    (dest / "stale.txt").write_text("old")  # must be gone after reinstall

    plasmoid.install_plasmoid(src=src, dest_dir=dest, klop_bin="/opt/bin/klop")

    assert not (dest / "stale.txt").exists()


class _Proc:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_add_to_panel_runs_plasmashell_script_and_reports_outcome():
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return _Proc("added\n")

    assert plasmoid.add_to_panel(run=run) == "added"
    cmd = calls[0]
    assert cmd[:4] == ["qdbus6", "org.kde.plasmashell", "/PlasmaShell",
                       "org.kde.PlasmaShell.evaluateScript"]
    assert '"org.trungld.klop"' in cmd[4]
    assert "addWidget" in cmd[4]


def test_add_to_panel_reports_already_present():
    assert plasmoid.add_to_panel(run=lambda cmd, **kw: _Proc("present")) == "present"


def test_add_to_panel_unavailable_without_plasmashell():
    def missing(cmd, **kw):
        raise FileNotFoundError("qdbus6")

    assert plasmoid.add_to_panel(run=missing) == "unavailable"
    assert plasmoid.add_to_panel(run=lambda cmd, **kw: _Proc("", 1)) == "unavailable"
