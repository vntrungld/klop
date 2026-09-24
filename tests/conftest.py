import os

import pytest
from PIL import Image


@pytest.fixture(autouse=True)
def _isolate_history(tmp_path, monkeypatch):
    # Point every test's history at its own tmp file; tests that need a
    # specific path override this with their own monkeypatch.setenv.
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(tmp_path / "history.jsonl"))


@pytest.fixture(autouse=True)
def _no_job_tracker(monkeypatch):
    # Headless CLI runs would otherwise put real progress cards on the
    # desktop; tests that exercise progress install their own fake.
    monkeypatch.setattr("klop.jobview._connect", lambda: None)


@pytest.fixture(autouse=True)
def _isolate_progress_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KLOP_PROGRESS_DIR", str(tmp_path / "progress"))


@pytest.fixture
def sample_png(tmp_path):
    p = tmp_path / "sample.png"
    # Noisy gradient so optimizers have something real to compress.
    img = Image.new("RGBA", (256, 256))
    px = img.load()
    for y in range(256):
        for x in range(256):
            px[x, y] = (x, y, (x * y) % 256, 255)
    img.save(p, "PNG")
    return p


@pytest.fixture
def sample_jpeg(tmp_path):
    p = tmp_path / "sample.jpg"
    img = Image.new("RGB", (256, 256))
    px = img.load()
    for y in range(256):
        for x in range(256):
            px[x, y] = (x, y, (x + y) % 256)
    img.save(p, "JPEG", quality=95)
    return p


@pytest.fixture(scope="session")
def qapp():
    # Headless Qt: use the offscreen platform plugin so widgets/tray can be
    # constructed in CI without a display server.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
