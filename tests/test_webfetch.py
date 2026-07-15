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
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(webfetch.subprocess, "run", fake_run)
    assert webfetch.copy_image_to_clipboard(img) is True
    assert calls["argv"][0] == "/usr/bin/wl-copy"
    assert "image/png" in calls["argv"]


def test_copy_to_clipboard_false_when_no_tool(tmp_path, monkeypatch):
    img = tmp_path / "a.png"
    Image.new("RGB", (4, 4)).save(img, "PNG")
    monkeypatch.setattr(webfetch.shutil, "which", lambda name: None)
    assert webfetch.copy_image_to_clipboard(img) is False
