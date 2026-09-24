"""Install the Klop Plasma applet from the package bundled with klop."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .servicemenu import resolve_exec

PLUGIN_ID = "org.trungld.klop"

# The applet package shipped inside the Python package (see pyproject force-include).
_PKG_SRC = Path(__file__).parent / "plasmoid_pkg"


def plasmoid_dest_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "plasma" / "plasmoids" / PLUGIN_ID


def _write_backend_js(pkg_dir: Path, klop_bin: str) -> None:
    code_dir = pkg_dir / "contents" / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    # A QML .pragma library so every representation shares one constant.
    (code_dir / "backend.js").write_text(
        f".pragma library\nvar KLOP_BIN = {json.dumps(klop_bin)};\n"
    )


def install_plasmoid(
    *, src: Path | None = None, dest_dir: Path | None = None, klop_bin: str | None = None
) -> Path:
    src = src or _PKG_SRC
    dest_dir = dest_dir or plasmoid_dest_dir()
    klop_bin = klop_bin or resolve_exec()
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(src, dest_dir)
    _write_backend_js(dest_dir, klop_bin)
    return dest_dir


# Plasma shell script: add the applet to the first panel unless some panel
# already has it. Prints the outcome so the caller can report it.
_ADD_TO_PANEL_JS = """
var id = %s;
var ps = panels();
var found = false;
for (var i = 0; i < ps.length; i++) {
    var ws = ps[i].widgets();
    for (var j = 0; j < ws.length; j++) {
        if (ws[j].type == id) found = true;
    }
}
if (found) print("present");
else if (ps.length == 0) print("no-panel");
else { ps[0].addWidget(id); print("added"); }
"""


def add_to_panel(*, run=subprocess.run) -> str:
    """Put the applet on the first panel via plasmashell's scripting API.

    Returns "added", "present", "no-panel", or "unavailable" when plasmashell
    (or qdbus6) cannot be reached.
    """
    script = _ADD_TO_PANEL_JS % json.dumps(PLUGIN_ID)
    try:
        proc = run(
            ["qdbus6", "org.kde.plasmashell", "/PlasmaShell",
             "org.kde.PlasmaShell.evaluateScript", script],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    if proc.returncode != 0:
        return "unavailable"
    out = proc.stdout.strip()
    return out if out in ("added", "present", "no-panel") else "unavailable"
