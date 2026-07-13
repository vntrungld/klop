from pathlib import Path

from clop_kde.media import MediaType, detect_media_type


def test_detect_png_by_magic(sample_png):
    assert detect_media_type(sample_png) == MediaType.PNG


def test_detect_jpeg_by_magic(sample_jpeg):
    assert detect_media_type(sample_jpeg) == MediaType.JPEG


def test_magic_bytes_beat_wrong_extension(sample_png, tmp_path):
    lying = tmp_path / "actually_png.jpg"
    lying.write_bytes(sample_png.read_bytes())
    assert detect_media_type(lying) == MediaType.PNG


def test_pdf_by_magic(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.7\n...")
    assert detect_media_type(p) == MediaType.PDF


def test_unknown_for_text(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_bytes(b"hello world")
    assert detect_media_type(p) == MediaType.UNKNOWN
