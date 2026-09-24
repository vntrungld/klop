import dataclasses

import pytest

from klop.config import (
    Config,
    apply_overrides,
    config_to_dict,
    load_config,
    save_config,
)


def test_config_to_dict_lists_pngquant_quality():
    d = config_to_dict(Config())
    assert d["pngquant_quality"] == [65, 80]  # tuple rendered as a JSON-friendly list
    assert d["png_lossy"] is True
    assert set(d) == {f.name for f in dataclasses.fields(Config)}


def test_save_then_load_round_trips_every_field(tmp_path):
    cfg = Config(png_lossy=False, pngquant_quality=(40, 60), jpeg_max_quality=70,
                 min_bytes_saved=5, concurrency=4, clipboard_watch=False)
    path = tmp_path / "sub" / "config.toml"
    save_config(cfg, path)  # also creates the missing parent dir
    assert load_config(path) == cfg


def test_apply_overrides_coerces_types():
    cfg = apply_overrides(
        Config(),
        {"png_lossy": "false", "jpeg_max_quality": "70", "pngquant_quality": "40,60"},
    )
    assert cfg.png_lossy is False
    assert cfg.jpeg_max_quality == 70
    assert cfg.pngquant_quality == (40, 60)


def test_apply_overrides_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown config key: bogus"):
        apply_overrides(Config(), {"bogus": "1"})


def test_apply_overrides_rejects_bad_values():
    with pytest.raises(ValueError):
        apply_overrides(Config(), {"jpeg_max_quality": "high"})
    with pytest.raises(ValueError):
        apply_overrides(Config(), {"png_lossy": "maybe"})
    with pytest.raises(ValueError):
        apply_overrides(Config(), {"pngquant_quality": "40"})  # needs two values


def test_save_config_is_atomic_and_leaves_no_temp(tmp_path):
    path = tmp_path / "config.toml"
    save_config(Config(), path)
    assert path.exists()
    assert list(path.parent.glob("*.tmp")) == []


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


def test_clipboard_watch_defaults_true(tmp_path):
    from klop.config import load_config

    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.clipboard_watch is True


def test_clipboard_watch_can_be_disabled(tmp_path):
    from klop.config import load_config

    p = tmp_path / "config.toml"
    p.write_text("clipboard_watch = false\n")
    assert load_config(p).clipboard_watch is False


def test_web_drop_dir_defaults_and_round_trips(tmp_path):
    assert Config().web_drop_dir == "~/Pictures/Klop"
    cfg = Config(web_drop_dir="~/Downloads/opt")
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    assert load_config(path).web_drop_dir == "~/Downloads/opt"


def test_apply_overrides_coerces_string_field():
    cfg = apply_overrides(Config(), {"web_drop_dir": "/tmp/klop out"})
    assert cfg.web_drop_dir == "/tmp/klop out"  # spaces preserved verbatim


def test_config_to_dict_includes_web_drop_dir():
    assert config_to_dict(Config())["web_drop_dir"] == "~/Pictures/Klop"


def test_toml_serializes_string_with_quotes(tmp_path):
    # a value containing a double-quote must round-trip through TOML
    cfg = Config(web_drop_dir='~/we"ird')
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    assert load_config(path).web_drop_dir == '~/we"ird'


def test_toml_serializes_string_with_backslash(tmp_path):
    cfg = Config(web_drop_dir=r"~/we\ird\path")
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    assert load_config(path).web_drop_dir == r"~/we\ird\path"


def test_new_optimizer_knobs_have_defaults():
    from klop.config import Config
    c = Config()
    assert c.webp_quality == 80
    assert c.gif_lossy == 0
    assert c.pdf_setting == "ebook"
    assert c.video_crf == 28
    assert c.video_codec == "libx264"
    assert c.video_preset == "medium"


def test_new_knobs_round_trip_through_toml(tmp_path):
    from klop.config import Config, save_config, load_config
    path = tmp_path / "config.toml"
    save_config(Config(webp_quality=70, video_crf=30, pdf_setting="screen"), path)
    loaded = load_config(path)
    assert loaded.webp_quality == 70
    assert loaded.video_crf == 30
    assert loaded.pdf_setting == "screen"


def test_new_knobs_apply_overrides():
    from klop.config import Config, apply_overrides
    c = apply_overrides(Config(), {"video_crf": "23", "video_codec": "libx265"})
    assert c.video_crf == 23
    assert c.video_codec == "libx265"


def test_video_threads_defaults_to_auto_and_round_trips(tmp_path):
    assert Config().video_threads == 0
    c = apply_overrides(Config(), {"video_threads": "4"})
    assert c.video_threads == 4
    path = tmp_path / "config.toml"
    save_config(c, path)
    assert load_config(path).video_threads == 4
