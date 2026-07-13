from __future__ import annotations

import re
import subprocess
import sys
from typing import Callable, Protocol

from PySide6.QtCore import SLOT, QObject, Slot
from PySide6.QtDBus import QDBusConnection

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

    _NOTIFY_REPLY_RE = re.compile(r"uint32\s+(\d+)")

    @staticmethod
    def _gvariant_string_literal(value: str) -> str:
        """Escape a Python str as a double-quoted GVariant text-format
        string literal (backslash and double-quote are the two characters
        GVariant's parser treats specially inside a quoted string)."""
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def send(self, summary, body, actions, icon):
        flat: list[str] = []
        for key, label in actions:
            flat.extend([key, label])
        # PySide6's QtDBus marshals a bare Python int as D-Bus int32 and a
        # list as "av" (QDBusMessage.setArguments), and even
        # QDBusInterface.callWithArgumentList — despite introspecting the
        # remote object — does not coerce the replaces_id scalar to uint32.
        # The resulting outgoing signature ("si...") mismatches
        # freedesktop's Notify ("su..."; replaces_id is uint32, actions is
        # "as"), and real daemons (e.g. KDE Plasma's) reject the call with
        # UnknownMethod. `gdbus call` parses each argument as a GVariant
        # text-format literal against the introspected method signature,
        # so it marshals correctly; shell out to it instead.
        actions_literal = "[" + ", ".join(self._gvariant_string_literal(a) for a in flat) + "]"
        argv = [
            "gdbus",
            "call",
            "--session",
            "-d",
            self._SERVICE,
            "-o",
            self._PATH,
            "-m",
            f"{self._SERVICE}.Notify",
            "--",
            self._gvariant_string_literal(self._app_name),
            "0",
            self._gvariant_string_literal(icon),
            self._gvariant_string_literal(summary),
            self._gvariant_string_literal(body),
            actions_literal,
            "{}",
            "-1",
        ]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"clop-kde: Notify failed to invoke gdbus: {exc}", file=sys.stderr)
            return 0
        if proc.returncode != 0:
            print(
                f"clop-kde: Notify failed: {proc.stderr.strip() or proc.stdout.strip()}",
                file=sys.stderr,
            )
            return 0
        match = self._NOTIFY_REPLY_RE.search(proc.stdout)
        return int(match.group(1)) if match else 0

    @Slot("uint", str)
    def _action_invoked(self, notification_id, action_key):
        if self.on_action:
            self.on_action(int(notification_id), str(action_key))

    @Slot("uint", "uint")
    def _notification_closed(self, notification_id, reason):
        if self.on_closed:
            self.on_closed(int(notification_id))
