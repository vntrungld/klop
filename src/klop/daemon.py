from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QFileSystemWatcher
from PySide6.QtWidgets import QApplication

from .app import TrayApp, load_tray_icon
from .capabilities import detect_capabilities
from .cli import _build_engine
from .clipboard import ClipboardWatcher, optimize_image_bytes
from .config import default_config_path, load_config
from .format import human_size, percent_saved
from .history import HistoryStore
from .notifier import DBusNotificationBackend, Notifier
from .overlay import ResultOverlay
from .queue import OptimizationQueue
from .results import ResultRouter


class Daemon(NamedTuple):
    tray: object
    queue: object
    notifier: object
    watcher: object
    overlay: object
    router: object
    config_watcher: object


def build_daemon(
    app, *, engine=None, backend=None, clipboard=None, overlay=None, history=None,
    config_path=None,
):
    engine = engine or _build_engine()
    config_path = Path(config_path) if config_path else default_config_path()
    config = load_config(config_path)
    # Mutable so a config reload reaches the clipboard optimizer closure.
    state = {"config": config}
    history = history or HistoryStore()

    def _undo_file(backup_id):
        engine.undo(backup_id)
        history.mark_undone(backup_id)

    queue = OptimizationQueue(optimize_fn=engine.optimize, concurrency=config.concurrency)
    app.aboutToQuit.connect(lambda: queue.wait_for_done(3000))
    backend = backend or DBusNotificationBackend()
    notifier = Notifier(backend=backend, undo_fn=_undo_file)
    overlay = overlay or ResultOverlay(undo_fn=_undo_file)
    tray = TrayApp(icon=load_tray_icon())

    router = ResultRouter(tray, overlay, notifier, history=history)
    queue.job_done.connect(router.on_job_done)
    queue.job_started.connect(router.on_job_started)

    # Always built so the panel widget can turn clipboard_watch on/off at
    # runtime; `enabled` gates the work.
    if clipboard is None:
        from PySide6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard()
    capabilities = detect_capabilities()

    def _optimize(png_bytes):
        return optimize_image_bytes(png_bytes, state["config"], capabilities)

    watcher = ClipboardWatcher(clipboard=clipboard, optimize_fn=_optimize)
    app.aboutToQuit.connect(lambda: watcher.wait_for_done(3000))

    def _on_clipboard_optimized(result):
        tray.record_saved(result.saved_bytes)
        history.record(
            "clipboard",
            "Clipboard image",
            None,
            result.original_size,
            result.new_size,
        )
        body = (
            f"{human_size(result.original_size)} → "
            f"{human_size(result.new_size)} "
            f"(-{percent_saved(result.original_size, result.new_size)}%)"
        )
        token = result.undo_token
        notifier.notify(
            "Clipboard image",
            body,
            undo=lambda: watcher.undo(token),
            undo_confirm="Restored image to clipboard",
        )

    watcher.optimized.connect(_on_clipboard_optimized)
    # The overlay is shared across sources (clipboard + file jobs); guard
    # the clipboard-driven dismiss by pending state so it can't destroy
    # a file result card that was shown while the clipboard job ran.
    watcher.started.connect(
        lambda png: overlay.show_pending("Clipboard image", png)
    )
    watcher.finished.connect(overlay.dismiss_if_pending)
    tray.enabled_action.toggled.connect(
        lambda checked: setattr(watcher, "enabled", checked)
    )
    tray.enabled_action.setChecked(config.clipboard_watch)
    watcher.enabled = config.clipboard_watch

    # The widget edits the config file (`klop config set`); pick changes up
    # live. Watch the directory too: save_config replaces the file atomically,
    # which drops the file from the watch list.
    config_watcher = QFileSystemWatcher()

    def _rewatch():
        paths = [str(config_path.parent)]
        if config_path.exists():
            paths.append(str(config_path))
        watched = config_watcher.files() + config_watcher.directories()
        missing = [p for p in paths if p not in watched]
        if missing:
            config_watcher.addPaths(missing)

    def _reload(_path=None):
        _rewatch()
        new = load_config(config_path)
        if new == state["config"]:
            return
        state["config"] = new
        tray.enabled_action.setChecked(new.clipboard_watch)

    if config_path.parent.exists():
        _rewatch()
    config_watcher.fileChanged.connect(_reload)
    config_watcher.directoryChanged.connect(_reload)

    return Daemon(
        tray=tray,
        queue=queue,
        notifier=notifier,
        watcher=watcher,
        overlay=overlay,
        router=router,
        config_watcher=config_watcher,
    )


def run_daemon(*, show_tray: bool = True) -> int:
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)  # windowless app; nothing else keeps it alive
    daemon = build_daemon(app)
    # With the panel widget installed the tray icon is redundant: the widget
    # shows the savings total and the clipboard toggle.
    if show_tray:
        daemon.tray.show()
    return app.exec()
