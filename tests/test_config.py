from clop_kde.config import Config, load_config


def test_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg == Config()
    assert cfg.png_lossy is True
    assert cfg.pngquant_quality == (65, 80)
    assert cfg.min_bytes_saved == 1


def test_partial_file_fills_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        "png_lossy = false\n"
        "jpeg_max_quality = 60\n"
        "pngquant_quality = [40, 70]\n"
    )
    cfg = load_config(p)
    assert cfg.png_lossy is False
    assert cfg.jpeg_max_quality == 60
    assert cfg.pngquant_quality == (40, 70)
    # Untouched keys keep defaults.
    assert cfg.concurrency == 2
    assert cfg.backup_retention_days == 7


def test_unknown_keys_are_ignored(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("bogus_key = 123\njpeg_max_quality = 50\n")
    cfg = load_config(p)
    assert cfg.jpeg_max_quality == 50
