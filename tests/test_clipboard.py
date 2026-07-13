from pathlib import Path

import pytest

from clop_kde.clipboard import content_hash, image_to_png_bytes, optimize_image_bytes
from clop_kde.config import Config


def test_content_hash_stable_and_distinct():
    assert content_hash(b"abc") == content_hash(b"abc")
    assert content_hash(b"abc") != content_hash(b"abd")


def test_image_to_png_bytes_roundtrip(qapp):
    from PySide6.QtGui import QImage

    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(0xFF0000)
    data = image_to_png_bytes(img)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    reloaded = QImage.fromData(data, "PNG")
    assert not reloaded.isNull()
    assert reloaded.width() == 4


def test_optimize_returns_smaller_bytes():
    def runner(cmd, stdout_path):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"y" * 10)
        return 0

    caps = {"pngquant": "/usr/bin/pngquant"}
    result = optimize_image_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000, Config(), caps, runner=runner)
    assert result is not None
    assert len(result) < 1008


def test_optimize_returns_none_when_not_smaller():
    def runner(cmd, stdout_path):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000)  # same size
        return 0

    caps = {"pngquant": "/usr/bin/pngquant"}
    assert optimize_image_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 1000, Config(), caps, runner=runner) is None


def test_optimize_returns_none_without_optimizer():
    def runner(cmd, stdout_path):
        raise AssertionError("runner must not be called when no optimizer is available")

    assert optimize_image_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100, Config(), {"pngquant": None}, runner=runner) is None


def test_optimize_returns_none_on_runner_failure():
    def runner(cmd, stdout_path):
        return 99  # pngquant "quality not met", writes nothing

    caps = {"pngquant": "/usr/bin/pngquant"}
    assert optimize_image_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100, Config(), caps, runner=runner) is None


@pytest.mark.skipif(__import__("shutil").which("pngquant") is None, reason="pngquant not installed")
def test_optimize_real_pngquant(qapp):
    from PySide6.QtGui import QImage

    img = QImage(256, 256, QImage.Format.Format_ARGB32)
    for y in range(256):
        for x in range(256):
            img.setPixel(x, y, (0xFF << 24) | (x << 16) | (y << 8) | ((x * y) % 256))
    png = image_to_png_bytes(img)
    result = optimize_image_bytes(png, Config(), {"pngquant": __import__("shutil").which("pngquant")})
    # Either it shrank (bytes) or it couldn't beat min_bytes_saved (None) — both are valid.
    assert result is None or len(result) < len(png)
