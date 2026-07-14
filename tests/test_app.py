from clop_kde import app as app_module
from clop_kde.app import TrayApp, load_tray_icon


def test_menu_has_no_file_picker_action(qapp):
    tray = TrayApp()
    # The file picker is gone; files are optimized via Dolphin (CLI) or the
    # always-on drop target, not a menu-driven QFileDialog.
    assert not hasattr(tray, "optimize_action")
    assert all(not a.text().startswith("Optimize files") for a in tray._menu.actions())


def test_enabled_action_defaults_checked_and_toggles(qapp):
    tray = TrayApp()
    assert tray.enabled_action.isChecked() is True
    tray.enabled_action.setChecked(False)
    assert tray.enabled_action.isChecked() is False


def test_load_tray_icon_returns_a_non_null_icon(qapp):
    icon = load_tray_icon()
    assert not icon.isNull()


def test_record_saved_accumulates_total_and_updates_text(qapp):
    tray = TrayApp()

    tray.record_saved(5000)
    tray.record_saved(3000)

    assert tray.saved_total() == 8000
    assert "Saved:" in tray.saved_action.text()
    assert "7.8KB" in tray.saved_action.text()  # 8000 bytes -> 7.8KB


def test_open_config_does_not_raise_when_xdg_open_is_missing(qapp, monkeypatch, tmp_path):
    tray = TrayApp()
    monkeypatch.setattr(app_module, "default_config_path", lambda: tmp_path / "clop-kde.toml")

    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("xdg-open not found")

    monkeypatch.setattr(app_module.subprocess, "Popen", raise_missing)

    tray._on_open_config()  # must not raise
