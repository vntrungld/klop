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


PNGQUANT = Optimizer("pngquant", "pngquant", _pngquant_cmd, use_stdout=False)
JPEGOPTIM = Optimizer("jpegoptim", "jpegoptim", _jpegoptim_cmd, use_stdout=True)

# First available optimizer per media type wins.
_REGISTRY: dict[MediaType, list[Optimizer]] = {
    MediaType.PNG: [PNGQUANT],
    MediaType.JPEG: [JPEGOPTIM],
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
