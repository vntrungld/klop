from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

from .config import Config
from .engine import _default_runner
from .media import MediaType
from .optimizers import select_optimizer


def image_to_png_bytes(image: QImage) -> bytes:
    """Serialize a QImage to PNG bytes."""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def content_hash(png_bytes: bytes) -> str:
    """Stable content key for loop-prevention."""
    return hashlib.sha1(png_bytes).hexdigest()


def optimize_image_bytes(png_bytes, config: Config, capabilities, runner=None) -> bytes | None:
    """Optimize PNG bytes, returning the smaller bytes or None (no optimizer,
    not smaller, or failure). No file backup — there is no persistent original."""
    optimizer = select_optimizer(MediaType.PNG, capabilities, config)
    if optimizer is None:
        return None
    run = runner or _default_runner
    original_size = len(png_bytes)
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "in.png"
        src.write_bytes(png_bytes)
        out = Path(tmpdir) / "out.png"
        cmd = optimizer.build_command(src, out, config)
        stdout_path = out if optimizer.use_stdout else None
        code = run(cmd, stdout_path)
        if code != 0 or not out.exists() or out.stat().st_size == 0:
            return None
        new_bytes = out.read_bytes()
    if original_size - len(new_bytes) < config.min_bytes_saved:
        return None
    return new_bytes
