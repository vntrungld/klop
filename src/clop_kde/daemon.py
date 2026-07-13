from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .app import TrayApp, load_tray_icon
from .cli import _build_engine
from .config import load_config
from .notifier import DBusNotificationBackend, Notifier
from .queue import OptimizationQueue


def build_daemon(app, *, engine=None, backend=None):
    engine = engine or _build_engine()
    config = load_config()
    queue = OptimizationQueue(optimize_fn=engine.optimize, concurrency=config.concurrency)
    backend = backend or DBusNotificationBackend()
    notifier = Notifier(backend=backend, undo_fn=engine.undo)
    tray = TrayApp(queue=queue, notifier=notifier, icon=load_tray_icon())
    return tray, queue, notifier


def run_daemon() -> int:
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)  # tray-only app; no windows keep it alive
    tray, _queue, _notifier = build_daemon(app)
    tray.show()
    return app.exec()
