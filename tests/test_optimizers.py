from pathlib import Path

from clop_kde.config import Config
from clop_kde.media import MediaType
from clop_kde.optimizers import (
    CWEBP,
    GIFSICLE,
    GS,
    JPEGOPTIM,
    PNGQUANT,
    VIPS_WEBP,
    select_optimizer,
    FFMPEG,
    VIPS_HEIC,
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


def test_gifsicle_command_shape():
    cfg = Config(gif_lossy=0)
    cmd = GIFSICLE.build_command(Path("/in.gif"), Path("/out.gif"), cfg)
    assert cmd[0] == "gifsicle"
    assert "-O3" in cmd
    assert "--lossy=0" not in " ".join(cmd)   # lossless when gif_lossy == 0
    assert cmd[cmd.index("-o") + 1] == "/out.gif"
    assert cmd[-1] == "/in.gif"
    assert GIFSICLE.use_stdout is False


def test_gifsicle_lossy_flag_when_enabled():
    cmd = GIFSICLE.build_command(Path("/in.gif"), Path("/out.gif"), Config(gif_lossy=30))
    assert "--lossy=30" in cmd


def test_cwebp_command_shape():
    cmd = CWEBP.build_command(Path("/in.webp"), Path("/out.webp"), Config(webp_quality=70))
    assert cmd[0] == "cwebp"
    assert cmd[cmd.index("-q") + 1] == "70"
    assert cmd[cmd.index("-o") + 1] == "/out.webp"
    assert cmd[-1] == "/in.webp"


def test_vips_webp_command_shape():
    cmd = VIPS_WEBP.build_command(Path("/in.webp"), Path("/out.webp"), Config(webp_quality=65))
    assert cmd[0] == "vips"
    assert cmd[1] == "copy"
    assert cmd[2] == "/in.webp"
    assert cmd[3].startswith("/out.webp[")
    assert "Q=65" in cmd[3]


def test_gs_command_shape():
    cmd = GS.build_command(Path("/in.pdf"), Path("/out.pdf"), Config(pdf_setting="screen"))
    assert cmd[0] == "gs"
    assert "-dPDFSETTINGS=/screen" in cmd
    assert "-sOutputFile=/out.pdf" in cmd
    assert cmd[-1] == "/in.pdf"


def test_gs_unknown_setting_falls_back_to_ebook():
    cmd = GS.build_command(Path("/in.pdf"), Path("/out.pdf"), Config(pdf_setting="bogus"))
    assert "-dPDFSETTINGS=/ebook" in cmd


def test_select_new_same_ext_optimizers():
    caps = {"gifsicle": "/x", "cwebp": "/x", "vips": "/x", "gs": "/x"}
    assert select_optimizer(MediaType.GIF, caps, Config()) is GIFSICLE
    assert select_optimizer(MediaType.WEBP, caps, Config()) is CWEBP
    assert select_optimizer(MediaType.PDF, caps, Config()) is GS
    # cwebp missing → vips fallback for WebP
    assert select_optimizer(MediaType.WEBP, {"vips": "/x"}, Config()) is VIPS_WEBP


def test_ffmpeg_command_shape_and_output_ext():
    cfg = Config(video_crf=30, video_codec="libx264", video_preset="fast")
    cmd = FFMPEG.build_command(Path("/in.mkv"), Path("/out.mp4"), cfg)
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-i") + 1] == "/in.mkv"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-crf") + 1] == "30"
    assert cmd[cmd.index("-preset") + 1] == "fast"
    # Re-encode audio to AAC so opus/vorbis (webm/mkv) remux into mp4 instead
    # of failing the whole convert.
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[-1] == "/out.mp4"          # output is the last arg
    assert FFMPEG.output_ext == ".mp4"


def test_vips_heic_command_shape_and_output_ext():
    cmd = VIPS_HEIC.build_command(Path("/in.heic"), Path("/out.jpg"), Config(jpeg_max_quality=75))
    assert cmd[0] == "vips"
    assert cmd[1] == "copy"
    assert cmd[2] == "/in.heic"
    assert cmd[3].startswith("/out.jpg[")
    assert "Q=75" in cmd[3]
    assert VIPS_HEIC.output_ext == ".jpg"


def test_existing_optimizers_default_output_ext_none():
    assert PNGQUANT.output_ext is None
    assert JPEGOPTIM.output_ext is None


def test_select_convert_optimizers():
    caps = {"ffmpeg": "/x", "vips": "/x"}
    assert select_optimizer(MediaType.VIDEO, caps, Config()) is FFMPEG
    assert select_optimizer(MediaType.HEIC, caps, Config()) is VIPS_HEIC
