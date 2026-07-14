from __future__ import annotations

import dataclasses
import os
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
    clipboard_watch: bool = True


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


_BOOL_TRUE = {"true", "1", "yes", "on"}
_BOOL_FALSE = {"false", "0", "no", "off"}


def config_to_dict(config: Config) -> dict:
    out: dict = {}
    for f in dataclasses.fields(config):
        value = getattr(config, f.name)
        out[f.name] = list(value) if isinstance(value, tuple) else value
    return out


def _coerce_like(current, key: str, raw: str):
    # bool is a subclass of int, so check it first.
    if isinstance(current, bool):
        v = raw.strip().lower()
        if v in _BOOL_TRUE:
            return True
        if v in _BOOL_FALSE:
            return False
        raise ValueError(f"invalid boolean for {key}: {raw!r}")
    if isinstance(current, tuple):
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != 2:
            raise ValueError(f"{key} expects two comma-separated ints, got: {raw!r}")
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            raise ValueError(f"invalid ints for {key}: {raw!r}")
    if isinstance(current, int):
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"invalid integer for {key}: {raw!r}")
    raise ValueError(f"unsupported config field: {key}")


def apply_overrides(config: Config, overrides: dict[str, str]) -> Config:
    updates = {}
    for key, raw in overrides.items():
        if key not in _FIELD_NAMES:
            raise ValueError(f"unknown config key: {key}")
        updates[key] = _coerce_like(getattr(config, key), key, raw)
    return dataclasses.replace(config, **updates)


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        return "[" + ", ".join(str(x) for x in value) + "]"
    if isinstance(value, int):
        return str(value)
    raise TypeError(f"cannot serialize {value!r} to TOML")


def save_config(config: Config, path: Path | None = None) -> None:
    if path is None:
        path = default_config_path()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{f.name} = {_toml_value(getattr(config, f.name))}"
             for f in dataclasses.fields(config)]
    text = "\n".join(lines) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
