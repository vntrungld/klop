from clop_kde import plasmoid


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

    result = plasmoid.install_plasmoid(src=src, dest_dir=dest, clop_bin="/opt/bin/clop-kde")

    assert result == dest
    assert (dest / "metadata.json").exists()
    assert (dest / "contents" / "ui" / "main.qml").exists()
    backend = (dest / "contents" / "code" / "backend.js").read_text()
    assert 'var CLOP_BIN = "/opt/bin/clop-kde"' in backend
    assert ".pragma library" in backend


def test_install_replaces_existing_dest(tmp_path):
    src = _fake_pkg(tmp_path / "src")
    dest = tmp_path / "out" / "org.trungld.klop"
    dest.mkdir(parents=True)
    (dest / "stale.txt").write_text("old")  # must be gone after reinstall

    plasmoid.install_plasmoid(src=src, dest_dir=dest, clop_bin="/opt/bin/clop-kde")

    assert not (dest / "stale.txt").exists()
