from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QRect, Qt, QUrl

from clop_kde.droptarget import DropTargetWindow, _urls_to_paths


def _url_mime(paths):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return md


class _FakeDrop:
    def __init__(self, mime):
        self._mime = mime

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        pass


def test_urls_to_paths_maps_local_files():
    md = _url_mime([Path("/tmp/a.png"), Path("/tmp/b.png")])
    assert _urls_to_paths(md) == [Path("/tmp/a.png"), Path("/tmp/b.png")]


def test_urls_to_paths_drops_non_local_urls():
    md = QMimeData()
    md.setUrls([QUrl("https://example.com/x.png")])
    assert _urls_to_paths(md) == []


def test_drop_submits_local_paths(qapp):
    submitted = []
    window = DropTargetWindow(submit_fn=lambda paths: submitted.append(paths))
    window.dropEvent(_FakeDrop(_url_mime([Path("/tmp/a.png")])))
    assert submitted == [[Path("/tmp/a.png")]]


def test_drop_with_no_local_files_submits_nothing(qapp):
    submitted = []
    window = DropTargetWindow(submit_fn=lambda paths: submitted.append(paths))
    window.dropEvent(_FakeDrop(QMimeData()))
    assert submitted == []


def test_drop_target_is_frameless_and_stays_on_top(qapp):
    window = DropTargetWindow(submit_fn=lambda paths: None)
    flags = window.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint


def test_position_at_corner_pins_window_to_bottom_right(qapp):
    window = DropTargetWindow(submit_fn=lambda paths: None)
    window.resize(240, 140)
    window.position_at_corner(QRect(0, 0, 1920, 1080), margin=24)
    # right/bottom edge sits `margin` px from the screen's available edge
    assert window.pos() == QPoint(1919 - 240 - 24, 1079 - 140 - 24)
