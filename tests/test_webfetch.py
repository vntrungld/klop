import subprocess
from pathlib import Path

import pytest
from PIL import Image

from clop_kde import webfetch


def _png_bytes(tmp_path):
    p = tmp_path / "src.png"
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(p, "PNG")
    return p.read_bytes()


def test_rejects_non_http_scheme(tmp_path):
    with pytest.raises(ValueError, match="scheme"):
        webfetch.download_image("ftp://x/y.png", dest_dir=tmp_path,
                                fetcher=lambda u, t: (b"", u))


def test_downloads_and_saves_image(tmp_path):
    data = _png_bytes(tmp_path)
    dest = tmp_path / "out"
    got = webfetch.download_image("https://ex.com/pic.png", dest_dir=dest,
                                  fetcher=lambda u, t: (data, u))
    assert got == dest / "pic.png"
    assert got.read_bytes() == data


def test_rejects_non_image_bytes(tmp_path):
    with pytest.raises(ValueError, match="not an image"):
        webfetch.download_image("https://ex.com/x", dest_dir=tmp_path,
                                fetcher=lambda u, t: (b"<html>nope</html>", u))


def test_rejects_oversize(tmp_path):
    data = _png_bytes(tmp_path)
    with pytest.raises(ValueError, match="too large"):
        webfetch.download_image("https://ex.com/big.png", dest_dir=tmp_path,
                                fetcher=lambda u, t: (data, u), max_bytes=len(data) - 1)


def test_appends_extension_when_url_has_none(tmp_path):
    data = _png_bytes(tmp_path)
    got = webfetch.download_image("https://ex.com/download?id=42", dest_dir=tmp_path,
                                  fetcher=lambda u, t: (data, u))
    assert got.suffix == ".png"  # detected from magic bytes; query stripped


def test_dedupes_existing_filename(tmp_path):
    data = _png_bytes(tmp_path)
    (tmp_path / "pic.png").write_bytes(b"existing")  # collision
    got = webfetch.download_image("https://ex.com/pic.png", dest_dir=tmp_path,
                                  fetcher=lambda u, t: (data, u))
    assert got.name == "pic-1.png"
    assert (tmp_path / "pic.png").read_bytes() == b"existing"  # not overwritten


def test_copy_to_clipboard_uses_wl_copy(tmp_path, monkeypatch):
    img = tmp_path / "a.png"
    Image.new("RGB", (4, 4)).save(img, "PNG")
    calls = {}
    monkeypatch.setattr(webfetch.shutil, "which",
                        lambda name: "/usr/bin/wl-copy" if name == "wl-copy" else None)

    def fake_run(argv, **kw):
        calls["argv"] = argv
        calls["kw"] = kw
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(webfetch.subprocess, "run", fake_run)
    assert webfetch.copy_image_to_clipboard(img) is True
    assert calls["argv"][0] == "/usr/bin/wl-copy"
    assert "image/png" in calls["argv"]
    # The forked wl-copy daemon inherits our stdout/stderr; if left connected
    # to a pipe (e.g. `clop-kde optimize-url | cat`), the daemon holds the
    # pipe open forever and the reader never sees EOF. Must be detached.
    assert calls["kw"].get("stdout") == subprocess.DEVNULL
    assert calls["kw"].get("stderr") == subprocess.DEVNULL


def test_copy_to_clipboard_false_when_no_tool(tmp_path, monkeypatch):
    img = tmp_path / "a.png"
    Image.new("RGB", (4, 4)).save(img, "PNG")
    monkeypatch.setattr(webfetch.shutil, "which", lambda name: None)
    assert webfetch.copy_image_to_clipboard(img) is False


def test_urllib_fetch_reads_only_up_to_cap(monkeypatch):
    import io
    payload = b"x" * 100

    class _Resp(io.BytesIO):
        def geturl(self):
            return "https://ex.com/big"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(webfetch.urllib.request, "urlopen",
                        lambda req, timeout: _Resp(payload))
    # here we test the fetcher directly returns at most cap+1 bytes.
    data, final = webfetch._urllib_fetch("https://ex.com/big", 5, cap=10)
    assert len(data) == 11  # cap + 1, proving the read is bounded by cap, not the 50MB constant
    assert final == "https://ex.com/big"
