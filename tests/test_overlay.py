from pathlib import Path

from PySide6.QtGui import QImage

from clop_kde.job import JobResult, JobStatus
from clop_kde.overlay import ResultOverlay, _drag_mime


def _write_png(path: Path) -> None:
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(0x3366CC)
    img.save(str(path), "PNG")


def _result(path, orig=8579, new=3431, backup_id="b1"):
    return JobResult(JobStatus.OPTIMIZED, path, orig, new, backup_id=backup_id)


def test_show_result_sets_text_and_thumbnail(qapp, tmp_path):
    p = tmp_path / "photo.png"
    _write_png(p)
    overlay = ResultOverlay()
    overlay.show_result(_result(p))
    assert "photo.png" in overlay.title_label.text()
    assert "60%" in overlay.savings_label.text()  # 8579 -> 3431 is -60%
    assert not overlay.thumb_label.pixmap().isNull()


def test_undo_button_invokes_undo_and_hides(qapp, tmp_path):
    p = tmp_path / "photo.png"
    _write_png(p)
    undone = []
    overlay = ResultOverlay(undo_fn=lambda bid: undone.append(bid))
    overlay.show_result(_result(p, 1000, 400, backup_id="B7"))
    assert overlay.isVisible()
    overlay.undo_button.click()
    assert undone == ["B7"]
    assert not overlay.isVisible()


def test_open_button_calls_open_fn(qapp, tmp_path):
    p = tmp_path / "photo.png"
    _write_png(p)
    opened = []
    overlay = ResultOverlay(open_fn=lambda path: opened.append(path))
    overlay.show_result(_result(p))
    overlay.open_button.click()
    assert opened == [p]


def test_null_pixmap_falls_back_without_error(qapp, tmp_path):
    p = tmp_path / "broken.png"
    p.write_bytes(b"not a png")
    overlay = ResultOverlay()
    overlay.show_result(_result(p))  # must not raise
    assert overlay.isVisible()


def test_drag_mime_carries_the_file_url(qapp, tmp_path):
    p = tmp_path / "photo.png"
    _write_png(p)
    md = _drag_mime(p)
    assert md.hasUrls()
    assert md.urls()[0].toLocalFile() == str(p)


def test_auto_dismiss_timer_hides(qapp, tmp_path):
    p = tmp_path / "photo.png"
    _write_png(p)
    overlay = ResultOverlay()
    overlay.show_result(_result(p))
    assert overlay.isVisible()
    overlay._timer.timeout.emit()  # simulate the dismiss timer firing
    assert not overlay.isVisible()
