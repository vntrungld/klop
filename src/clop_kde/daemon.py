from __future__ import annotations

import sys
from typing import NamedTuple

from PySide6.QtWidgets import QApplication

from .app import TrayApp, load_tray_icon
from .capabilities import detect_capabilities
from .cli import _build_engine
from .clipboard import ClipboardWatcher, optimize_image_bytes
from .config import load_config
from .droptarget import DropTargetWindow
from .format import human_size, percent_saved
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
    droptarget: object
    router: object


def build_daemon(app, *, engine=None, backend=None, clipboard=None, overlay=None, droptarget=None):
    engine = engine or _build_engine()
    config = load_config()
    queue = OptimizationQueue(optimize_fn=engine.optimize, concurrency=config.concurrency)
    app.aboutToQuit.connect(lambda: queue.wait_for_done(3000))
    backend = backend or DBusNotificationBackend()
    notifier = Notifier(backend=backend, undo_fn=engine.undo)
    overlay = overlay or ResultOverlay(undo_fn=engine.undo)
    droptarget = droptarget or DropTargetWindow(submit_fn=queue.submit)
    tray = TrayApp(queue=queue, icon=load_tray_icon(), drop_toggle_fn=droptarget.toggle)

    router = ResultRouter(tray, overlay, notifier)
    queue.job_done.connect(router.on_job_done)
    queue.job_started.connect(router.on_job_started)

    watcher = None
    if config.clipboard_watch:
        if clipboard is None:
            from PySide6.QtGui import QGuiApplication

            clipboard = QGuiApplication.clipboard()
        capabilities = detect_capabilities()

        def _optimize(png_bytes):
            return optimize_image_bytes(png_bytes, config, capabilities)

        watcher = ClipboardWatcher(clipboard=clipboard, optimize_fn=_optimize)
        app.aboutToQuit.connect(lambda: watcher.wait_for_done(3000))

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

    return Daemon(
        tray=tray,
        queue=queue,
        notifier=notifier,
        watcher=watcher,
        overlay=overlay,
        droptarget=droptarget,
        router=router,
    )


def run_daemon() -> int:
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)  # tray-only app; no windows keep it alive
    daemon = build_daemon(app)
    daemon.tray.show()
    return app.exec()
