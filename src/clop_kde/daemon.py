from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .app import TrayApp, load_tray_icon
from .capabilities import detect_capabilities
from .cli import _build_engine
from .clipboard import ClipboardWatcher, optimize_image_bytes
from .config import load_config
from .format import human_size, percent_saved
from .notifier import DBusNotificationBackend, Notifier
from .queue import OptimizationQueue


def build_daemon(app, *, engine=None, backend=None, clipboard=None):
    engine = engine or _build_engine()
    config = load_config()
    queue = OptimizationQueue(optimize_fn=engine.optimize, concurrency=config.concurrency)
    backend = backend or DBusNotificationBackend()
    notifier = Notifier(backend=backend, undo_fn=engine.undo)
    tray = TrayApp(queue=queue, notifier=notifier, icon=load_tray_icon())

    watcher = None
    if config.clipboard_watch:
        if clipboard is None:
            from PySide6.QtGui import QGuiApplication

            clipboard = QGuiApplication.clipboard()
        capabilities = detect_capabilities()

        def _optimize(png_bytes):
            return optimize_image_bytes(png_bytes, config, capabilities)

        watcher = ClipboardWatcher(clipboard=clipboard, optimize_fn=_optimize)

        def _on_clipboard_optimized(result):
            tray.record_saved(result.saved_bytes)
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
        tray.enabled_action.toggled.connect(
            lambda checked: setattr(watcher, "enabled", checked)
        )

    return tray, queue, notifier, watcher


def run_daemon() -> int:
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)  # tray-only app; no windows keep it alive
    tray, _queue, _notifier, _watcher = build_daemon(app)
    tray.show()
    return app.exec()
