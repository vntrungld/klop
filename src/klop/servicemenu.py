"""Dolphin (KIO) service-menu integration.

Generates and installs the ``.desktop`` file that puts an "Optimize with Klop"
entry in Dolphin's right-click menu. It reuses the ``klop optimize`` CLI as
its backend, so no extra process is needed.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_ASSET_ICON = Path(__file__).parent / "assets" / "tray.svg"
_FILE_NAME = "klop-optimize.desktop"

# Raster image types klop optimizes today (video/PDF/HEIC are later milestones).
_MIME_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


def _default_icon() -> str:
    return str(_ASSET_ICON) if _ASSET_ICON.exists() else "image-x-generic"


def resolve_exec() -> str:
    """Absolute path to the ``klop`` executable.

    Dolphin does not inherit the user's shell PATH, so the service menu must
    call klop by absolute path.
    """
    found = shutil.which("klop")
    if found:
        return found
    argv0 = Path(sys.argv[0]).resolve()
    if argv0.name == "klop":
        return str(argv0)
    return "klop"


def servicemenu_dir() -> Path:
    """The KF6 user service-menu directory (respects XDG_DATA_HOME)."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "kio" / "servicemenus"


def desktop_entry(exec_path: str, icon: str = "image-x-generic") -> str:
    mimes = ";".join(_MIME_TYPES) + ";"
    return (
        "[Desktop Entry]\n"
        "Type=Service\n"
        "Name=Optimize with Klop\n"
        "ServiceTypes=KonqPopupMenu/Plugin\n"
        f"MimeType={mimes}\n"
        "Actions=optimizeWithKlop;\n"
        "X-KDE-Priority=TopLevel\n"
        "\n"
        "[Desktop Action optimizeWithKlop]\n"
        "Name=Optimize with Klop\n"
        f"Icon={icon}\n"
        f'Exec="{exec_path}" optimize %F\n'
    )


def install(*, exec_path: str | None = None, dest_dir: Path | None = None) -> Path:
    """Write the service menu and mark it executable (required by KF6)."""
    exec_path = exec_path or resolve_exec()
    dest_dir = dest_dir or servicemenu_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _FILE_NAME
    dest.write_text(desktop_entry(exec_path, icon=_default_icon()))
    dest.chmod(0o755)
    return dest
