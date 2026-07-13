from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from .config import default_config_path
from .format import human_size
from .job import JobResult, JobStatus

_ICON_PATH = Path(__file__).parent / "assets" / "tray.svg"


def load_tray_icon() -> QIcon:
    if _ICON_PATH.exists():
        icon = QIcon(str(_ICON_PATH))
        if not icon.isNull():
            return icon
    return QIcon.fromTheme("image-x-generic")


def _default_pick_files() -> list[Path]:
    paths, _ = QFileDialog.getOpenFileNames(None, "Optimize files")
    return [Path(p) for p in paths]


class TrayApp:
    """System-tray front end: a menu that feeds files to the queue and shows
    a running savings total."""

    def __init__(
        self,
        queue,
        notifier,
        *,
        icon: QIcon | None = None,
        pick_files: Callable[[], list[Path]] = _default_pick_files,
    ):
        self._queue = queue
        self._notifier = notifier
        self._pick_files = pick_files
        self._enabled = True
        self._saved_total = 0

        self._menu = QMenu()
        self.optimize_action = self._menu.addAction("Optimize files…")
        self.optimize_action.triggered.connect(self._on_optimize)

        self.saved_action = self._menu.addAction("Saved: 0B")
        self.saved_action.setEnabled(False)

        self._menu.addSeparator()

        self.enabled_action = self._menu.addAction("Enabled")
        self.enabled_action.setCheckable(True)
        self.enabled_action.setChecked(True)
        self.enabled_action.toggled.connect(self._on_enabled_toggled)

        self._menu.addAction("Open config").triggered.connect(self._on_open_config)
        self._menu.addAction("Quit").triggered.connect(self._on_quit)

        self._tray = QSystemTrayIcon(icon or load_tray_icon())
        self._tray.setContextMenu(self._menu)
        self._tray.setToolTip("Clop-KDE")

        queue.job_done.connect(self._on_job_done)

    def show(self) -> None:
        self._tray.show()

    def saved_total(self) -> int:
        return self._saved_total

    def _on_optimize(self, _checked: bool = False) -> None:
        if not self._enabled:
            return
        paths = self._pick_files()
        if paths:
            self._queue.submit(paths)

    def _on_enabled_toggled(self, checked: bool) -> None:
        self._enabled = checked
        self.optimize_action.setEnabled(checked)

    def record_saved(self, saved_bytes: int) -> None:
        self._saved_total += saved_bytes
        self.saved_action.setText(f"Saved: {human_size(self._saved_total)}")

    def _on_job_done(self, result: JobResult) -> None:
        if result.status == JobStatus.OPTIMIZED:
            self.record_saved(result.saved_bytes)
        self._notifier.notify_result(result)

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
