from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


def _urls_to_paths(mime) -> list[Path]:
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]


class DropTargetWindow(QWidget):
    """An always-on-top window that optimizes files dragged onto it."""

    def __init__(self, submit_fn, parent=None):
        super().__init__(
            parent, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self._submit_fn = submit_fn
        self.setAcceptDrops(True)
        self.setWindowTitle("Clop-KDE — Drop to optimize")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Drop images here to optimize"))
        self.resize(240, 140)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = _urls_to_paths(event.mimeData())
        if paths:
            self._submit_fn(paths)
        event.acceptProposedAction()
