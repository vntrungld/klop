"""Progress for headless runs via KDE's job tracker (org.kde.JobViewServer).

Plasma shows a tracked job as a notification with a progress bar — the same
card a Dolphin file copy gets — so ``klop optimize`` launched from the service
menu or the panel widget can show "Optimizing x.png · 2 of 5 files" while it
works, then turn that card into the run's summary.

A job view lives only as long as the D-Bus connection that requested it, so
one-shot ``gdbus`` calls (see ``notify``) can't drive it; and PySide6's QtDBus
can't marshal the unsigned ints these methods take. jeepney keeps one plain
connection open for the whole run and stays Qt-free.

Every call is best-effort: without a job tracker (no Plasma session, no D-Bus)
the progress object quietly does nothing and ``finish`` returns False so the
caller can fall back to a regular notification.
"""

from __future__ import annotations

import sys

_SERVICE = "org.kde.kuiserver"
_SERVER_PATH = "/JobViewServer"
_SERVER_IFACE = "org.kde.JobViewServer"
_VIEW_IFACE = "org.kde.JobViewV2"


def _connect():
    """Open a session-bus connection, or None when D-Bus is unavailable."""
    try:
        from jeepney.io.blocking import open_dbus_connection

        return open_dbus_connection(bus="SESSION")
    except Exception:  # noqa: BLE001 - no bus, no jeepney: progress is optional
        return None


class JobProgress:
    """One tracked job; create with ``JobProgress.start``."""

    def __init__(self, conn=None, path: str | None = None, total: int = 0):
        self._conn = conn
        self._path = path
        self._total = total

    @classmethod
    def start(cls, total: int, *, app_name: str = "Klop", icon: str = "") -> JobProgress:
        conn = _connect()
        if conn is None:
            return cls()
        job = cls(conn, total=total)
        reply = job._call(_SERVER_PATH, _SERVER_IFACE, "requestView", "ssi", (app_name, icon, 0))
        if not reply:
            job.close()
            return cls()
        job._path = reply[0]
        job._view("setTotalAmount", "ts", (total, "files"))
        return job

    @property
    def active(self) -> bool:
        return self._path is not None

    def update(self, done: int, total: int, name: str) -> None:
        """Report that file ``done + 1`` of ``total`` (``name``) is starting."""
        self._view("setInfoMessage", "s", (f"Optimizing {name}",))
        self._view("setProcessedAmount", "ts", (done, "files"))
        self.set_percent(done * 100 // max(total, 1))

    def set_percent(self, percent: int) -> None:
        """Move the bar within a file, e.g. while a video encodes."""
        self._view("setPercent", "u", (percent,))

    def finish(self, message: str, *, error: str = "") -> bool:
        """End the job, leaving ``message`` on the finished card (or ``error``
        marking it failed). Returns False when no card was shown."""
        if not self.active:
            return False
        if not error:
            self._view("setProcessedAmount", "ts", (self._total, "files"))
            self._view("setPercent", "u", (100,))
            self._view("setInfoMessage", "s", (message,))
        ok = self._view("terminate", "s", (error,)) is not None
        self.close()
        return ok

    def close(self) -> None:
        self._path = None
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def _view(self, method: str, signature: str, args: tuple):
        if not self.active:
            return None
        return self._call(self._path, _VIEW_IFACE, method, signature, args)

    def _call(self, path: str, iface: str, method: str, signature: str, args: tuple):
        """Call a method and return its reply body, or None on any failure."""
        if self._conn is None:
            return None
        try:
            from jeepney import DBusAddress, MessageType, new_method_call

            addr = DBusAddress(path, bus_name=_SERVICE, interface=iface)
            reply = self._conn.send_and_get_reply(
                new_method_call(addr, method, signature, args), timeout=2
            )
        except Exception as exc:  # noqa: BLE001
            print(f"klop: job progress {method} failed: {exc}", file=sys.stderr)
            return None
        if reply.header.message_type != MessageType.method_return:
            return None
        return reply.body
