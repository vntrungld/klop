from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


def _urls_to_paths(mime) -> list[Path]:
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]


class DropTargetWindow(QWidget):
    """A frameless, always-on-top drop zone pinned to a screen corner — like
    Clop on macOS. It stays visible for the daemon's lifetime and optimizes any
    files dragged onto it."""

    def __init__(self, submit_fn, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint,
        )
        self._submit_fn = submit_fn
        self.setAcceptDrops(True)
        self.setWindowTitle("Clop-KDE — Drop to optimize")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Drop images here to optimize"))
        self.resize(240, 140)

    def position_at_corner(self, geometry: QRect, margin: int = 24) -> None:
        """Pin the window's bottom-right corner `margin` px inside the given
        screen geometry (typically the primary screen's available area)."""
        x = geometry.right() - self.width() - margin
        y = geometry.bottom() - self.height() - margin
        self.move(x, y)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = _urls_to_paths(event.mimeData())
        if paths:
            self._submit_fn(paths)
        event.acceptProposedAction()
