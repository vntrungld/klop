import shutil

from clop_kde.capabilities import KNOWN_TOOLS, detect_capabilities, has_tool


def test_detects_present_tool(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    caps = detect_capabilities(["pngquant", "jpegoptim"])
    assert caps == {"pngquant": "/usr/bin/pngquant", "jpegoptim": "/usr/bin/jpegoptim"}
    assert has_tool(caps, "pngquant") is True


def test_detects_absent_tool(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    caps = detect_capabilities(["pngquant"])
    assert caps == {"pngquant": None}
    assert has_tool(caps, "pngquant") is False


def test_default_scans_known_tools(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    caps = detect_capabilities()
    assert set(caps) == set(KNOWN_TOOLS)
