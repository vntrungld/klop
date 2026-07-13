from pathlib import Path

from clop_kde import app as app_module
from clop_kde.app import TrayApp, load_tray_icon


class FakeQueue:
    def __init__(self):
        self.submitted = []

    def submit(self, paths):
        self.submitted.append(list(paths))


def test_optimize_action_submits_picked_files(qapp):
    queue = FakeQueue()
    picked = [Path("/tmp/a.png"), Path("/tmp/b.png")]
    tray = TrayApp(queue=queue, pick_files=lambda: picked)

    tray.optimize_action.trigger()

    assert queue.submitted == [picked]


def test_disabling_greys_out_the_picker_and_blocks_submit(qapp):
    queue = FakeQueue()
    tray = TrayApp(queue=queue, pick_files=lambda: [Path("/tmp/a.png")])

    tray.enabled_action.setChecked(False)  # fires toggled(False)

    assert tray.optimize_action.isEnabled() is False
    tray.optimize_action.trigger()  # disabled QAction: triggered is not emitted
    assert queue.submitted == []


def test_show_drop_target_action_calls_toggle(qapp):
    toggled = []
    tray = TrayApp(queue=FakeQueue(), pick_files=lambda: [], drop_toggle_fn=lambda: toggled.append(1))
    tray.drop_action.trigger()
    assert toggled == [1]


def test_load_tray_icon_returns_a_non_null_icon(qapp):
    icon = load_tray_icon()
    assert not icon.isNull()


def test_record_saved_accumulates_total_and_updates_text(qapp):
    queue = FakeQueue()
    tray = TrayApp(queue=queue, pick_files=lambda: [])

    tray.record_saved(5000)
    tray.record_saved(3000)

    assert tray.saved_total() == 8000
    assert "Saved:" in tray.saved_action.text()
    assert "7.8KB" in tray.saved_action.text()  # 8000 bytes -> 7.8KB


def test_open_config_does_not_raise_when_xdg_open_is_missing(qapp, monkeypatch, tmp_path):
    queue = FakeQueue()
    tray = TrayApp(queue=queue, pick_files=lambda: [])
    monkeypatch.setattr(app_module, "default_config_path", lambda: tmp_path / "clop-kde.toml")

    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("xdg-open not found")

    monkeypatch.setattr(app_module.subprocess, "Popen", raise_missing)

    tray._on_open_config()  # must not raise
