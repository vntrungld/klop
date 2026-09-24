"""Fire-and-forget desktop notifications over org.freedesktop.Notifications.

Kept free of Qt so short-lived, headless entrypoints (the ``optimize`` CLI that
Dolphin's service menu calls) can post a notification without spinning up a Qt
event loop. The daemon's ``DBusNotificationBackend`` delegates its ``send`` here
too, so the tricky GVariant/gdbus marshalling lives in one place.
"""

from __future__ import annotations

import re
import subprocess
import sys

_SERVICE = "org.freedesktop.Notifications"
_PATH = "/org/freedesktop/Notifications"
_NOTIFY_REPLY_RE = re.compile(r"uint32\s+(\d+)")


def _gvariant_string_literal(value: str) -> str:
    """Escape a Python str as a double-quoted GVariant text-format string
    literal (backslash and double-quote are the two characters GVariant's
    parser treats specially inside a quoted string)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def send_notification(
    summary: str,
    body: str,
    *,
    actions: tuple[tuple[str, str], ...] = (),
    icon: str = "",
    app_name: str = "Klop",
    timeout: float = 5,
) -> int:
    """Post a notification via ``gdbus call ... Notify``; return the daemon's
    notification id (0 if it could not be sent). Never raises.

    ``gdbus`` parses each argument as a GVariant text-format literal against
    the introspected Notify signature ("susssasa{sv}i"), so replaces_id and the
    actions array marshal with the correct types — which PySide6's QtDBus does
    not do reliably for this method.
    """
    flat: list[str] = []
    for key, label in actions:
        flat.extend([key, label])
    actions_literal = "[" + ", ".join(_gvariant_string_literal(a) for a in flat) + "]"
    argv = [
        "gdbus",
        "call",
        "--session",
        "-d",
        _SERVICE,
        "-o",
        _PATH,
        "-m",
        f"{_SERVICE}.Notify",
        "--",
        _gvariant_string_literal(app_name),
        "0",
        _gvariant_string_literal(icon),
        _gvariant_string_literal(summary),
        _gvariant_string_literal(body),
        actions_literal,
        "{}",
        "-1",
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"klop: Notify failed to invoke gdbus: {exc}", file=sys.stderr)
        return 0
    if proc.returncode != 0:
        print(
            f"klop: Notify failed: {proc.stderr.strip() or proc.stdout.strip()}",
            file=sys.stderr,
        )
        return 0
    match = _NOTIFY_REPLY_RE.search(proc.stdout)
    return int(match.group(1)) if match else 0


def wait_for_action(
    summary: str,
    body: str,
    actions: tuple[tuple[str, str], ...],
    *,
    icon: str = "",
    app_name: str = "Klop",
    timeout: float = 600,
) -> str | None:
    """Post a notification with action buttons and block until it closes;
    return the clicked action's key, or None if it was dismissed, expired, or
    could not be shown. Never raises.

    Uses ``notify-send --action``, which waits for the daemon's ActionInvoked /
    NotificationClosed signals — something a one-shot ``gdbus call`` can't do.
    """
    argv = ["notify-send", f"--app-name={app_name}"]
    if icon:
        argv.append(f"--icon={icon}")
    argv += [f"--action={key}={label}" for key, label in actions]
    argv += ["--", summary, body]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"klop: notify-send failed: {exc}", file=sys.stderr)
        return None
    return proc.stdout.strip() or None
