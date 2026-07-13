from __future__ import annotations

import dataclasses
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    png_lossy: bool = True
    pngquant_quality: tuple[int, int] = (65, 80)
    jpeg_max_quality: int = 80
    min_bytes_saved: int = 1
    concurrency: int = 2
    backup_retention_days: int = 7
    backup_max_bytes: int = 500 * 1024 * 1024


def default_config_path() -> Path:
    return Path.home() / ".config" / "clop-kde" / "config.toml"


_FIELD_NAMES = {f.name for f in dataclasses.fields(Config)}


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML; missing file or absent keys fall back to defaults."""
    if path is None:
        path = default_config_path()
    try:
        raw = tomllib.loads(Path(path).read_text())
    except OSError:
        return Config()

    kwargs = {}
    for key, value in raw.items():
        if key not in _FIELD_NAMES:
            continue
        if key == "pngquant_quality" and isinstance(value, list):
            value = tuple(value)
        kwargs[key] = value
    return Config(**kwargs)
