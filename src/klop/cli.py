from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import webfetch
from .backup import BackupStore
from .capabilities import KNOWN_TOOLS, detect_capabilities
from .config import apply_overrides, config_to_dict, load_config, save_config
from .engine import Engine
from .format import human_size, percent_saved
from .history import HistoryStore
from .job import JobResult, JobStatus, OptimizationJob
from .notify import send_notification, wait_for_action


_ICON_PATH = Path(__file__).parent / "assets" / "tray.svg"


def _notify_icon() -> str:
    return str(_ICON_PATH) if _ICON_PATH.exists() else "image-x-generic"


def _backup_root() -> Path:
    override = os.environ.get("KLOP_BACKUP_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "klop" / "backups"


def _build_engine() -> Engine:
    return Engine(
        config=load_config(),
        backup_store=BackupStore(_backup_root()),
        capabilities=detect_capabilities(),
    )


def _cmd_caps(_args) -> int:
    caps = detect_capabilities(KNOWN_TOOLS)
    for name in KNOWN_TOOLS:
        path = caps.get(name)
        print(f"{name:12} {path or '(not found)'}")
    return 0


def _optimize_summary(
    optimized: list[JobResult], others: int, errors: int
) -> tuple[str, str] | None:
    """Build the (summary, body) desktop-notification text for a run, or None
    when there is nothing worth announcing."""
    n = len(optimized)
    if n == 1 and others == 0 and errors == 0:
        r = optimized[0]
        pct = percent_saved(r.original_size, r.new_size)
        return r.path.name, (
            f"{human_size(r.original_size)} → {human_size(r.new_size)} (-{pct}%)"
        )
    if n >= 1:
        saved = sum(r.saved_bytes for r in optimized)
        pct = percent_saved(
            sum(r.original_size for r in optimized),
            sum(r.new_size for r in optimized),
        )
        body = f"Optimized {n} files · saved {human_size(saved)} (-{pct}%)"
        if others:
            body += f" · {others} unchanged"
        if errors:
            body += f" · {errors} failed"
        return "Klop", body
    if errors:
        return "Klop", f"{errors} file(s) failed to optimize"
    if others:
        return "Klop", f"Nothing to optimize ({others} file(s) unchanged)"
    return None


def _cmd_optimize(args) -> int:
    engine = _build_engine()
    history = HistoryStore()
    exit_code = 0
    optimized: list[JobResult] = []
    others = 0
    errors = 0
    for raw in args.files:
        path = Path(raw)
        if not path.exists():
            print(f"error: file not found: {path}", file=sys.stderr)
            exit_code = 1
            errors += 1
            continue
        result = engine.optimize(OptimizationJob(source_path=path))
        if result.status == JobStatus.OPTIMIZED:
            print(
                f"optimized {result.path.name}: "
                f"{human_size(result.original_size)} -> {human_size(result.new_size)} "
                f"(saved {human_size(result.saved_bytes)}, undo id {result.backup_id})"
            )
            history.record(
                "file",
                result.path.name,
                str(result.path),
                result.original_size,
                result.new_size,
                result.backup_id,
            )
            optimized.append(result)
        elif result.status == JobStatus.ERROR:
            print(f"error {path.name}: {result.message}", file=sys.stderr)
            exit_code = 1
            errors += 1
            continue
        else:
            print(f"{result.status.value} {path.name}: {result.message}")
            others += 1

    # Dolphin's service menu runs us with no terminal, so stdout goes nowhere;
    # surface a desktop notification there. In an interactive shell the printed
    # output is enough, so stay quiet.
    if not sys.stdout.isatty():
        summary = _optimize_summary(optimized, others, errors)
        if summary is not None:
            send_notification(summary[0], summary[1], icon=_notify_icon())
    return exit_code


def _cmd_undo(args) -> int:
    store = BackupStore(_backup_root())
    try:
        restored = store.restore(args.backup_id)
    except KeyError:
        print(f"error: unknown backup id: {args.backup_id}", file=sys.stderr)
        return 1
    HistoryStore().mark_undone(args.backup_id)
    print(f"restored {restored}")
    return 0


def _cmd_history(args) -> int:
    entries = HistoryStore().entries()
    if args.json:
        print(json.dumps([e.to_dict() for e in entries]))
        return 0
    if not entries:
        print("no optimizations yet")
        return 0
    for e in entries:
        mark = "*" if e.undoable else " "  # * marks an undoable row
        line = (
            f"{mark} {e.kind:9} {e.name:24.24} "
            f"{human_size(e.original_size)} -> {human_size(e.new_size)} "
            f"(saved {human_size(e.saved_bytes)})"
        )
        if e.undone:
            line += " [undone]"
        print(line)
    return 0


def _cmd_install_dolphin(_args) -> int:
    from .servicemenu import install

    dest = install()
    print(f"installed Dolphin service menu: {dest}")
    print("Right-click an image in Dolphin → 'Optimize with Klop'.")
    print("If it doesn't appear yet, restart Dolphin (or run kbuildsycoca6).")
    return 0


def _cmd_config_get(args) -> int:
    data = config_to_dict(load_config())
    if args.json:
        print(json.dumps(data))
    else:
        for key, value in data.items():
            print(f"{key} = {value}")
    return 0


def _cmd_config_set(args) -> int:
    overrides: dict[str, str] = {}
    for item in args.assignments:
        if "=" not in item:
            print(f"error: expected key=value, got: {item}", file=sys.stderr)
            return 2
        key, value = item.split("=", 1)
        overrides[key.strip()] = value.strip()
    try:
        updated = apply_overrides(load_config(), overrides)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    save_config(updated)
    print(json.dumps(config_to_dict(updated)))
    return 0


def _cmd_install_plasmoid(_args) -> int:
    from .plasmoid import install_plasmoid

    dest = install_plasmoid()
    print(f"installed Klop plasmoid: {dest}")
    print("Add the 'Klop' widget to a panel (right-click a panel → Add Widgets).")
    print("If it does not appear, restart plasmashell:")
    print("  kquitapp6 plasmashell && kstart plasmashell")
    return 0


def _cmd_optimize_url(args) -> int:
    dest_dir = Path(load_config().web_drop_dir).expanduser()
    # The URLs are alternative sources for one image, tried in order: a
    # browser drag of a linked image (e.g. Facebook) carries both the <img src>
    # and the link's HTML page, and only one of them is the actual image.
    path = None
    for url in args.urls:
        try:
            path = webfetch.download_image(url, dest_dir=dest_dir)
            break
        except ValueError as exc:
            error = exc
    if path is None:
        print(f"error: {error}", file=sys.stderr)
        if not sys.stdout.isatty():
            send_notification("Klop", f"Could not fetch image: {error}", icon=_notify_icon())
        return 1

    engine = _build_engine()
    history = HistoryStore()
    result = engine.optimize(OptimizationJob(source_path=path))
    copied = webfetch.copy_image_to_clipboard(result.path)

    if result.status == JobStatus.OPTIMIZED:
        print(
            f"optimized {result.path.name}: "
            f"{human_size(result.original_size)} -> {human_size(result.new_size)} "
            f"(saved {human_size(result.saved_bytes)}, undo id {result.backup_id})"
        )
        history.record(
            "file", result.path.name, str(result.path),
            result.original_size, result.new_size, result.backup_id,
        )
    elif result.status == JobStatus.ERROR:
        print(f"error {path.name}: {result.message}", file=sys.stderr)
        return 1
    else:
        print(f"{result.status.value} {path.name}: {result.message}")

    print(f"saved {result.path}")

    if not sys.stdout.isatty():
        if result.status == JobStatus.OPTIMIZED:
            pct = percent_saved(result.original_size, result.new_size)
            summary = result.path.name
            body = f"{human_size(result.original_size)} → {human_size(result.new_size)} (-{pct}%)"
        else:
            summary = "Klop"
            body = f"Saved {result.path.name}"
        body += f"\nSaved to {dest_dir}" + (" · copied" if copied else "")
        _spawn_saved_notification(result.path, summary, body)
    return 0


def _spawn_saved_notification(path: Path, summary: str, body: str) -> None:
    """Show the result notification from a detached child: its Copy / Open
    folder buttons need a process that outlives this one, and the plasmoid
    counts the job as running until this process (and its pipes) finish."""
    try:
        subprocess.Popen(
            [sys.executable, "-m", "klop.cli", "notify-saved", str(path), summary, body],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        send_notification(summary, body, icon=_notify_icon())


def _open_in_file_manager(path: Path) -> None:
    dolphin = shutil.which("dolphin")
    argv = [dolphin, "--select", str(path)] if dolphin else ["xdg-open", str(path.parent)]
    try:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        print(f"error: could not open file manager: {exc}", file=sys.stderr)


def _cmd_notify_saved(args) -> int:
    path = Path(args.path)
    action = wait_for_action(
        args.summary, args.body,
        (("copy", "Copy"), ("open", "Open folder")),
        icon=_notify_icon(),
    )
    if action == "copy":
        webfetch.copy_image_to_clipboard(path)
    elif action == "open":
        _open_in_file_manager(path)
    return 0


def _cmd_copy(args) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"error: no such file: {path}", file=sys.stderr)
        return 1
    if webfetch.copy_image_to_clipboard(path):
        return 0
    print("error: could not copy image to clipboard", file=sys.stderr)
    return 1


def _cmd_daemon(_args) -> int:
    from .daemon import run_daemon  # lazy: keeps Qt out of the headless CLI import path

    return run_daemon()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="klop")
    sub = parser.add_subparsers(dest="command", required=True)

    p_opt = sub.add_parser("optimize", help="optimize one or more files")
    p_opt.add_argument("files", nargs="+")
    p_opt.set_defaults(func=_cmd_optimize)

    p_opturl = sub.add_parser("optimize-url", help="download, optimize, save, and copy an image URL")
    p_opturl.add_argument(
        "urls", nargs="+", metavar="url",
        help="image URL; extra URLs are fallbacks for the same image, tried in order",
    )
    p_opturl.set_defaults(func=_cmd_optimize_url)

    # Internal: the detached notification process spawned by optimize-url.
    p_nsaved = sub.add_parser("notify-saved")
    p_nsaved.add_argument("path")
    p_nsaved.add_argument("summary")
    p_nsaved.add_argument("body")
    p_nsaved.set_defaults(func=_cmd_notify_saved)

    p_copy = sub.add_parser("copy", help="copy an image file to the clipboard")
    p_copy.add_argument("path")
    p_copy.set_defaults(func=_cmd_copy)

    p_undo = sub.add_parser("undo", help="restore a backed-up original")
    p_undo.add_argument("backup_id")
    p_undo.set_defaults(func=_cmd_undo)

    p_hist = sub.add_parser("history", help="show optimization history")
    p_hist.add_argument("--json", action="store_true", help="output as JSON")
    p_hist.set_defaults(func=_cmd_history)

    p_caps = sub.add_parser("caps", help="show detected optimizer tools")
    p_caps.set_defaults(func=_cmd_caps)

    p_daemon = sub.add_parser("daemon", help="run the system-tray daemon")
    p_daemon.set_defaults(func=_cmd_daemon)

    p_install = sub.add_parser(
        "install-dolphin", help="install the Dolphin right-click 'Optimize with Klop' menu"
    )
    p_install.set_defaults(func=_cmd_install_dolphin)

    p_plasmoid = sub.add_parser(
        "install-plasmoid", help="install the Klop Plasma panel widget"
    )
    p_plasmoid.set_defaults(func=_cmd_install_plasmoid)

    p_config = sub.add_parser("config", help="get or set optimizer settings")
    csub = p_config.add_subparsers(dest="config_cmd", required=True)
    p_cget = csub.add_parser("get", help="print current config")
    p_cget.add_argument("--json", action="store_true", help="output as JSON")
    p_cget.set_defaults(func=_cmd_config_get)
    p_cset = csub.add_parser("set", help="set config keys (key=value ...)")
    p_cset.add_argument("assignments", nargs="+", metavar="key=value")
    p_cset.set_defaults(func=_cmd_config_set)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
