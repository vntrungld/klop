from pathlib import Path

from clop_kde.config import Config
from clop_kde.media import MediaType
from clop_kde.optimizers import (
    JPEGOPTIM,
    PNGQUANT,
    select_optimizer,
)


def test_pngquant_command_shape():
    cfg = Config(pngquant_quality=(40, 70))
    cmd = PNGQUANT.build_command(Path("/in.png"), Path("/out.png"), cfg)
    assert cmd[0] == "pngquant"
    assert "--quality=40-70" in cmd
    assert "--output" in cmd
    assert cmd[cmd.index("--output") + 1] == "/out.png"
    assert cmd[-1] == "/in.png"
    assert PNGQUANT.use_stdout is False


def test_jpegoptim_command_shape():
    cfg = Config(jpeg_max_quality=60)
    cmd = JPEGOPTIM.build_command(Path("/in.jpg"), Path("/out.jpg"), cfg)
    assert cmd[0] == "jpegoptim"
    assert "--max=60" in cmd
    assert "--stdout" in cmd
    assert cmd[-1] == "/in.jpg"
    assert JPEGOPTIM.use_stdout is True


def test_select_prefers_available_tool():
    caps = {"pngquant": "/usr/bin/pngquant", "jpegoptim": None}
    assert select_optimizer(MediaType.PNG, caps, Config()) is PNGQUANT
    assert select_optimizer(MediaType.JPEG, caps, Config()) is None


def test_select_unknown_media_returns_none():
    caps = {"pngquant": "/usr/bin/pngquant"}
    assert select_optimizer(MediaType.UNKNOWN, caps, Config()) is None
    assert select_optimizer(MediaType.PDF, caps, Config()) is None
