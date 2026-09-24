from __future__ import annotations

from typing import Callable, Protocol

from PySide6.QtCore import SLOT, QObject, Slot
from PySide6.QtDBus import QDBusConnection

from .format import human_size, percent_saved
from .job import JobResult, JobStatus
from .notify import send_notification


class NotificationBackend(Protocol):
    on_action: Callable[[int, str], None] | None
    on_closed: Callable[[int], None] | None

    def send(
        self, summary: str, body: str, actions: list[tuple[str, str]], icon: str
    ) -> int: ...


class Notifier(QObject):
    """Turns results into desktop notifications and handles the Undo action.

    Undo is a per-notification callback, so both file-restore (M1) and
    clipboard-restore (M2) go through the same path."""

    def __init__(self, backend, undo_fn: Callable[[str], object] | None = None,
                 icon: str = "", parent=None):
        super().__init__(parent)
        self._backend = backend
        self._undo_fn = undo_fn
        self._icon = icon
        # notification id -> (undo_callback, undo_confirm_text_or_None)
        self._undo_map: dict[int, tuple[Callable[[], object], str | None]] = {}
        backend.on_action = self._on_action
        backend.on_closed = self._on_closed

    def notify(self, summary: str, body: str, *,
               undo: Callable[[], object] | None = None,
               undo_confirm: str | None = None,
               icon: str | None = None) -> int:
        actions = [("undo", "Undo")] if undo is not None else []
        nid = self._backend.send(summary, body, actions,
                                 self._icon if icon is None else icon)
        if undo is not None:
            self._undo_map[nid] = (undo, undo_confirm)
        return nid

    def notify_result(self, result: JobResult) -> None:
        name = result.path.name
        if result.status == JobStatus.OPTIMIZED and result.backup_id:
            body = (
                f"{human_size(result.original_size)} → "
                f"{human_size(result.new_size)} "
                f"(-{percent_saved(result.original_size, result.new_size)}%)"
            )
            backup_id = result.backup_id
            self.notify(name, body,
                        undo=lambda: self._undo_fn(backup_id) if self._undo_fn else None,
                        undo_confirm=f"Restored {name}")
        elif result.status == JobStatus.ERROR:
            self.notify(name, f"Optimization failed: {result.message}")
        # UNCHANGED / SKIPPED: intentionally silent

    def _on_action(self, notification_id: int, action_key: str) -> None:
        if action_key != "undo":
            return
        entry = self._undo_map.pop(notification_id, None)
        if entry is None:
            return
        undo, undo_confirm = entry
        undo()
        if undo_confirm is not None:
            self._backend.send(undo_confirm, undo_confirm, [], self._icon)

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

    def __init__(self, app_name: str = "Klop", parent=None):
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
        # Marshalling lives in the Qt-free notify module so the headless CLI
        # can reuse it; see notify.send_notification for why we shell out to
        # gdbus rather than use PySide6's QtDBus for the Notify call.
        return send_notification(
            summary, body, actions=tuple(actions), icon=icon, app_name=self._app_name
        )

    @Slot("uint", str)
    def _action_invoked(self, notification_id, action_key):
        if self.on_action:
            self.on_action(int(notification_id), str(action_key))

    @Slot("uint", "uint")
    def _notification_closed(self, notification_id, reason):
        if self.on_closed:
            self.on_closed(int(notification_id))
