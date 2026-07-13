from __future__ import annotations

from typing import Callable, Protocol

from PySide6.QtCore import SLOT, QObject, Slot
from PySide6.QtDBus import QDBusConnection, QDBusMessage

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
        self._backend.send(f"Restored {name}", f"Restored {name}", [], self._icon)

    def _on_closed(self, notification_id: int) -> None:
        self._undo_map.pop(notification_id, None)


class DBusNotificationBackend(QObject):
    """Real backend over org.freedesktop.Notifications. The Notifier logic
    itself is covered via a fake backend; this adapter additionally has its
    own headless send() smoke tests (see tests/test_notifier.py) confirming
    it degrades to a no-op instead of raising when no notifications daemon
    is present on the bus."""

    _SERVICE = "org.freedesktop.Notifications"
    _PATH = "/org/freedesktop/Notifications"

    def __init__(self, app_name: str = "Clop-KDE", parent=None):
        super().__init__(parent)
        self.on_action: Callable[[int, str], None] | None = None
        self.on_closed: Callable[[int], None] | None = None
        self._app_name = app_name
        self._bus = QDBusConnection.sessionBus()
        # QDBusConnection.connect requires a QObject receiver + a SLOT()
        # signature string in PySide6 6.11; a bound Python method is not
        # accepted as the receiver/slot pair.
        self._bus.connect(
            self._SERVICE,
            self._PATH,
            self._SERVICE,
            "ActionInvoked",
            self,
            SLOT("_action_invoked(uint,QString)"),
        )
        self._bus.connect(
            self._SERVICE,
            self._PATH,
            self._SERVICE,
            "NotificationClosed",
            self,
            SLOT("_notification_closed(uint,uint)"),
        )

    def send(self, summary, body, actions, icon):
        flat: list[str] = []
        for key, label in actions:
            flat.extend([key, label])
        msg = QDBusMessage.createMethodCall(
            self._SERVICE, self._PATH, self._SERVICE, "Notify"
        )
        # replaces_id (arg 2) is spec'd as uint32 ("u"); a bare Python 0
        # marshals as int32 via QDBusMessage.setArguments in PySide6, which
        # KDE/GNOME notification daemons accept leniently. Forcing a true
        # uint32 scalar isn't practical from Python here (QVariant isn't
        # exposed and QDBusArgument has no typed scalar append), so we leave
        # it as-is per the freedesktop spec's lenient real-world servers.
        msg.setArguments([self._app_name, 0, icon, summary, body, flat, {}, -1])
        try:
            reply = self._bus.call(msg)
            args = reply.arguments()
            return int(args[0]) if args else 0
        except Exception:
            return 0

    @Slot("uint", str)
    def _action_invoked(self, notification_id, action_key):
        if self.on_action:
            self.on_action(int(notification_id), str(action_key))

    @Slot("uint", "uint")
    def _notification_closed(self, notification_id, reason):
        if self.on_closed:
            self.on_closed(int(notification_id))
