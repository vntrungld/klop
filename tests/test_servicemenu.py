import os
import stat

from klop import servicemenu


def test_desktop_entry_wires_exec_action_and_mimetypes():
    entry = servicemenu.desktop_entry("/opt/bin/klop", icon="/x/icon.svg")

    assert "[Desktop Entry]" in entry
    assert "Type=Service" in entry
    # a top-level Name keeps desktop-file-validate from erroring on a missing
    # required key
    assert entry.split("[Desktop Action", 1)[0].count("Name=Optimize with Klop") == 1
    # the CLI backend is reused as the service-menu backend; %F passes the
    # selected local files
    assert 'Exec="/opt/bin/klop" optimize %F' in entry
    assert "Actions=optimizeWithKlop;" in entry
    assert "[Desktop Action optimizeWithKlop]" in entry
    assert "Name=Optimize with Klop" in entry
    assert "Icon=/x/icon.svg" in entry
    for mime in ("image/png", "image/jpeg", "image/gif", "image/webp"):
        assert mime in entry


def test_servicemenu_dir_honours_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert servicemenu.servicemenu_dir() == tmp_path / "data" / "kio" / "servicemenus"


def test_install_writes_executable_desktop_file(tmp_path):
    dest = servicemenu.install(exec_path="/opt/bin/klop", dest_dir=tmp_path)

    assert dest.parent == tmp_path
    assert dest.suffix == ".desktop"
    text = dest.read_text()
    assert 'Exec="/opt/bin/klop" optimize %F' in text
    # KF6 requires the service-menu file to be executable
    mode = dest.stat().st_mode
    assert mode & stat.S_IXUSR


def test_install_creates_missing_dest_dir(tmp_path):
    nested = tmp_path / "kio" / "servicemenus"
    dest = servicemenu.install(exec_path="/opt/bin/klop", dest_dir=nested)
    assert dest.exists()
    assert os.path.isdir(nested)
