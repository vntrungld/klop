from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .config import default_config_path
from .format import human_size

_ICON_PATH = Path(__file__).parent / "assets" / "tray.svg"


def load_tray_icon() -> QIcon:
    if _ICON_PATH.exists():
        icon = QIcon(str(_ICON_PATH))
        if not icon.isNull():
            return icon
    return QIcon.fromTheme("image-x-generic")


class TrayApp:
    """System-tray front end: shows a running savings total and an enable
    toggle. Files are optimized via Dolphin (the CLI) or the always-on drop
    target, not from the menu."""

    def __init__(self, *, icon: QIcon | None = None):
        self._saved_total = 0

        self._menu = QMenu()
        self.saved_action = self._menu.addAction("Saved: 0B")
        self.saved_action.setEnabled(False)

        self._menu.addSeparator()

        self.enabled_action = self._menu.addAction("Enabled")
        self.enabled_action.setCheckable(True)
        self.enabled_action.setChecked(True)

        self._menu.addAction("Open config").triggered.connect(self._on_open_config)
        self._menu.addAction("Quit").triggered.connect(self._on_quit)

        self._tray = QSystemTrayIcon(icon or load_tray_icon())
        self._tray.setContextMenu(self._menu)
        self._tray.setToolTip("Clop-KDE")

    def show(self) -> None:
        self._tray.show()

    def saved_total(self) -> int:
        return self._saved_total

    def record_saved(self, saved_bytes: int) -> None:
        self._saved_total += saved_bytes
        self.saved_action.setText(f"Saved: {human_size(self._saved_total)}")

    def _on_open_config(self, _checked: bool = False) -> None:
        path = default_config_path()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")
        try:
            subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            self._tray.showMessage("Clop-KDE", f"Could not open config: {path}")

    def _on_quit(self, _checked: bool = False) -> None:
        QApplication.quit()
