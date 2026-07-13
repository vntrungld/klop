from __future__ import annotations

from typing import Callable, Protocol

from PySide6.QtCore import QObject, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface

from .format import human_size, percent_saved
from .job import JobResult, JobStatus


class NotificationBackend(Protocol):
    on_action: Callable[[int, str], None] | None
    on_closed: Callable[[int], None] | None

    def send(
        self, summary: str, body: str, actions: list[tuple[str, str]], icon: str
    ) -> int: ...


class Notifier(QObject):
    """Turns JobResults into desktop notifications and handles the Undo action."""

    def __init__(self, backend, undo_fn: Callable[[str], object], icon: str = "", parent=None):
        super().__init__(parent)
        self._backend = backend
        self._undo_fn = undo_fn
        self._icon = icon
        # notification id -> (backup_id, filename)
        self._undo_map: dict[int, tuple[str, str]] = {}
        backend.on_action = self._on_action
        backend.on_closed = self._on_closed

    def notify_result(self, result: JobResult) -> None:
        name = result.path.name
        if result.status == JobStatus.OPTIMIZED and result.backup_id:
            body = (
                f"{human_size(result.original_size)} → "
                f"{human_size(result.new_size)} "
                f"(-{percent_saved(result.original_size, result.new_size)}%)"
            )
            nid = self._backend.send(name, body, [("undo", "Undo")], self._icon)
            self._undo_map[nid] = (result.backup_id, name)
        elif result.status == JobStatus.ERROR:
            self._backend.send(name, f"Optimization failed: {result.message}", [], self._icon)
        # UNCHANGED / SKIPPED: intentionally silent

    def _on_action(self, notification_id: int, action_key: str) -> None:
        if action_key != "undo":
            return
        entry = self._undo_map.pop(notification_id, None)
        if entry is None:
            return
        backup_id, name = entry
        self._undo_fn(backup_id)
        self._backend.send("Restored", f"Restored {name}", [], self._icon)

    def _on_closed(self, notification_id: int) -> None:
        self._undo_map.pop(notification_id, None)


class DBusNotificationBackend(QObject):
    """Real backend over org.freedesktop.Notifications. Not unit-tested; the
    Notifier logic is covered via a fake backend, and this adapter is exercised
    by the Task 5 manual smoke test."""

    _SERVICE = "org.freedesktop.Notifications"
    _PATH = "/org/freedesktop/Notifications"

    def __init__(self, app_name: str = "Clop-KDE", parent=None):
        super().__init__(parent)
        self.on_action: Callable[[int, str], None] | None = None
        self.on_closed: Callable[[int], None] | None = None
        self._app_name = app_name
        self._bus = QDBusConnection.sessionBus()
        self._iface = QDBusInterface(self._SERVICE, self._PATH, self._SERVICE, self._bus)
        self._bus.connect(
            self._SERVICE, self._PATH, self._SERVICE, "ActionInvoked", self._action_invoked
        )
        self._bus.connect(
            self._SERVICE, self._PATH, self._SERVICE, "NotificationClosed", self._notification_closed
        )

    def send(self, summary, body, actions, icon):
        flat: list[str] = []
        for key, label in actions:
            flat.extend([key, label])
        reply = self._iface.call(
            "Notify", self._app_name, 0, icon, summary, body, flat, {}, -1
        )
        args = reply.arguments()
        return int(args[0]) if args else 0

    @Slot("uint", str)
    def _action_invoked(self, notification_id, action_key):
        if self.on_action:
            self.on_action(int(notification_id), str(action_key))

    @Slot("uint", "uint")
    def _notification_closed(self, notification_id, reason):
        if self.on_closed:
            self.on_closed(int(notification_id))
