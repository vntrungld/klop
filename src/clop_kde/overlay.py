from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QMimeData, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QDrag, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .format import human_size, percent_saved
from .job import JobResult

_DISMISS_MS = 4000
_THUMB = 96


def _default_open(path: Path) -> None:
    subprocess.Popen(["xdg-open", str(path)])


def _drag_mime(path: Path) -> QMimeData:
    """Mime carrying the file as text/uri-list so it can be dropped into other apps."""
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(path))])
    return md


class ResultOverlay(QWidget):
    """A frameless floating card shown when a file is optimized: thumbnail,
    savings, and Undo / Open / drag-out actions. Auto-dismisses; hover pauses."""

    def __init__(
        self,
        undo_fn: Callable[[str], object] | None = None,
        open_fn: Callable[[Path], None] = _default_open,
        parent=None,
    ):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._undo_fn = undo_fn
        self._open_fn = open_fn
        self._path: Path | None = None
        self._backup_id: str | None = None
        self._drag_start: QPoint | None = None
        self._pending = False

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(_THUMB, _THUMB)
        self.title_label = QLabel()
        self.savings_label = QLabel()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate / busy
        self.progress_bar.hide()

        self.undo_button = QPushButton("Undo")
        self.open_button = QPushButton("Open")
        self.undo_button.clicked.connect(self._on_undo)
        self.open_button.clicked.connect(self._on_open)

        self.button_row = QHBoxLayout()
        self.button_row.addWidget(self.undo_button)
        self.button_row.addWidget(self.open_button)
        # (M6 downscale buttons are appended to button_row here)

        text_col = QVBoxLayout()
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.savings_label)
        text_col.addWidget(self.progress_bar)
        text_col.addLayout(self.button_row)

        root = QHBoxLayout(self)
        root.addWidget(self.thumb_label)
        root.addLayout(text_col)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    def _set_thumbnail(self, source) -> None:
        pixmap = QPixmap()
        if isinstance(source, (str, Path)):
            pixmap = QPixmap(str(source))
        elif isinstance(source, (bytes, bytearray)):
            pixmap.loadFromData(bytes(source))
        if pixmap.isNull():
            self.thumb_label.setPixmap(
                QIcon.fromTheme("image-x-generic").pixmap(_THUMB, _THUMB)
            )
        else:
            self.thumb_label.setPixmap(
                pixmap.scaled(
                    _THUMB,
                    _THUMB,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def show_pending(self, title: str, thumbnail_source=None) -> None:
        self._path = None
        self._backup_id = None
        self._set_thumbnail(thumbnail_source)
        self.title_label.setText(f"Optimizing {title}…")
        self.savings_label.clear()
        self.progress_bar.show()
        self.undo_button.hide()
        self.open_button.hide()
        self._timer.stop()  # a pending card stays until the result replaces it
        self._reposition()
        self.show()
        self.raise_()
        self._pending = True

    def show_result(self, result: JobResult) -> None:
        self._pending = False
        self._path = Path(result.path)
        self._backup_id = result.backup_id
        self._set_thumbnail(self._path)
        self.title_label.setText(self._path.name)
        self.savings_label.setText(
            f"{human_size(result.original_size)} → "
            f"{human_size(result.new_size)} "
            f"(-{percent_saved(result.original_size, result.new_size)}%)"
        )
        self.progress_bar.hide()
        self.undo_button.show()
        self.open_button.show()
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(_DISMISS_MS)

    def dismiss(self) -> None:
        self._timer.stop()
        self._pending = False
        self.hide()

    def dismiss_if_pending(self) -> None:
        """Dismiss only if a pending card is showing — so a clipboard job
        finishing cannot tear down a file result card on the shared overlay."""
        if self._pending:
            self.dismiss()

    def _reposition(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.adjustSize()
        margin = 24
        self.move(
            geo.right() - self.width() - margin,
            geo.bottom() - self.height() - margin,
        )

    def _on_undo(self) -> None:
        backup_id = self._backup_id
        self._backup_id = None
        if backup_id is None:
            self.dismiss()
            return
        if self._undo_fn is not None:
            self._undo_fn(backup_id)
        self.dismiss()

    def _on_open(self) -> None:
        if self._path is None:
            return
        try:
            self._open_fn(self._path)
        except OSError:
            pass

    def enterEvent(self, event):
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isVisible():
            self._timer.start(_DISMISS_MS)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_start is not None
            and self._path is not None
            and (event.position().toPoint() - self._drag_start).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            drag = QDrag(self)
            drag.setMimeData(_drag_mime(self._path))
            self._drag_start = None
            self._timer.stop()
            drag.exec(Qt.DropAction.CopyAction)
        super().mouseMoveEvent(event)
