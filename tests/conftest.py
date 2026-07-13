import pytest
from PIL import Image


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
