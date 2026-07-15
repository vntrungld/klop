from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .media import MediaType


@dataclass(frozen=True)
class Optimizer:
    name: str
    tool: str
    _builder: Callable[[Path, Path, Config], list[str]]
    use_stdout: bool = False
    output_ext: str | None = None   # None = keep source suffix; ".jpg"/".mp4" = convert

    def build_command(self, inp: Path, out: Path, cfg: Config) -> list[str]:
        return self._builder(inp, out, cfg)


def _pngquant_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    lo, hi = cfg.pngquant_quality
    return [
        "pngquant",
        f"--quality={lo}-{hi}",
        "--force",
        "--skip-if-larger",
        "--strip",
        "--output",
        str(out),
        "--",
        str(inp),
    ]


def _jpegoptim_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    return [
        "jpegoptim",
        f"--max={cfg.jpeg_max_quality}",
        "--strip-all",
        "--stdout",
        "--",
        str(inp),
    ]


def _gifsicle_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    cmd = ["gifsicle", "-O3"]
    if cfg.gif_lossy > 0:
        cmd.append(f"--lossy={cfg.gif_lossy}")
    cmd += ["-o", str(out), "--", str(inp)]
    return cmd


def _cwebp_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    return ["cwebp", "-q", str(cfg.webp_quality), "-mt", "-o", str(out), str(inp)]


def _vips_webp_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    return ["vips", "copy", str(inp), f"{out}[Q={cfg.webp_quality},strip]"]


_PDF_SETTINGS = {"screen", "ebook", "printer", "prepress"}


def _gs_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    setting = cfg.pdf_setting if cfg.pdf_setting in _PDF_SETTINGS else "ebook"
    return [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS=/{setting}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={out}",
        str(inp),
    ]


def _ffmpeg_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(inp),
        "-c:v",
        cfg.video_codec,
        "-crf",
        str(cfg.video_crf),
        "-preset",
        cfg.video_preset,
        "-c:a",
        "copy",
        str(out),
    ]


def _vips_heic_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    return ["vips", "copy", str(inp), f"{out}[Q={cfg.jpeg_max_quality},strip]"]


PNGQUANT = Optimizer("pngquant", "pngquant", _pngquant_cmd, use_stdout=False)
JPEGOPTIM = Optimizer("jpegoptim", "jpegoptim", _jpegoptim_cmd, use_stdout=True)
GIFSICLE = Optimizer("gifsicle", "gifsicle", _gifsicle_cmd, use_stdout=False)
CWEBP = Optimizer("cwebp", "cwebp", _cwebp_cmd, use_stdout=False)
VIPS_WEBP = Optimizer("vips", "vips", _vips_webp_cmd, use_stdout=False)
GS = Optimizer("gs", "gs", _gs_cmd, use_stdout=False)
FFMPEG = Optimizer("ffmpeg", "ffmpeg", _ffmpeg_cmd, use_stdout=False, output_ext=".mp4")
VIPS_HEIC = Optimizer("vips", "vips", _vips_heic_cmd, use_stdout=False, output_ext=".jpg")

# First available optimizer per media type wins.
_REGISTRY: dict[MediaType, list[Optimizer]] = {
    MediaType.PNG: [PNGQUANT],
    MediaType.JPEG: [JPEGOPTIM],
    MediaType.GIF: [GIFSICLE],
    MediaType.WEBP: [CWEBP, VIPS_WEBP],
    MediaType.PDF: [GS],
    MediaType.VIDEO: [FFMPEG],
    MediaType.HEIC: [VIPS_HEIC],
}


def select_optimizer(
    media_type: MediaType, caps: dict[str, str | None], cfg: Config
) -> Optimizer | None:
    for opt in _REGISTRY.get(media_type, []):
        if caps.get(opt.tool) is not None:
            return opt
    return None


def expected_tools(media_type: MediaType) -> list[str]:
    """Tool names registered for a media type, in preference order."""
    return [opt.tool for opt in _REGISTRY.get(media_type, [])]
