"""systemd user service for the Klop daemon.

Plasma 6 starts its session through systemd, so a user unit bound to
``graphical-session.target`` starts the daemon at login with the session
environment (WAYLAND_DISPLAY, DBUS_SESSION_BUS_ADDRESS, ...) and stops it at
logout.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .servicemenu import resolve_exec

UNIT_NAME = "klop-daemon.service"


def unit_dir() -> Path:
    """The systemd user unit directory (respects XDG_CONFIG_HOME)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "systemd" / "user"


def legacy_autostart_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "autostart" / "klop-daemon.desktop"


def unit_text(exec_path: str) -> str:
    return (
        "[Unit]\n"
        "Description=Klop clipboard/overlay daemon\n"
        "PartOf=graphical-session.target\n"
        "After=graphical-session.target\n"
        "\n"
        "[Service]\n"
        f'ExecStart="{exec_path}" daemon --no-tray\n'
        "Restart=on-failure\n"
        "RestartSec=3\n"
        "\n"
        "[Install]\n"
        "WantedBy=graphical-session.target\n"
    )


def install_service(
    *, exec_path: str | None = None, dest_dir: Path | None = None, run=subprocess.run
) -> Path:
    """Write the unit, then enable and (re)start it.

    Also removes the XDG autostart entry older setups used, which would
    otherwise start a second daemon at login.
    """
    exec_path = exec_path or resolve_exec()
    dest_dir = dest_dir or unit_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / UNIT_NAME
    dest.write_text(unit_text(exec_path))

    legacy_autostart_path().unlink(missing_ok=True)

    run(["systemctl", "--user", "daemon-reload"], check=True)
    run(["systemctl", "--user", "enable", UNIT_NAME], check=True)
    # restart (not start) so a reinstall picks up a new ExecStart.
    run(["systemctl", "--user", "restart", UNIT_NAME], check=True)
    return dest
