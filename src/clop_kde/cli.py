from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .backup import BackupStore
from .capabilities import KNOWN_TOOLS, detect_capabilities
from .config import load_config
from .engine import Engine
from .format import human_size
from .history import HistoryStore
from .job import JobStatus, OptimizationJob


def _backup_root() -> Path:
    override = os.environ.get("CLOP_KDE_BACKUP_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "clop-kde" / "backups"


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


def _cmd_optimize(args) -> int:
    engine = _build_engine()
    history = HistoryStore()
    exit_code = 0
    for raw in args.files:
        path = Path(raw)
        if not path.exists():
            print(f"error: file not found: {path}", file=sys.stderr)
            exit_code = 1
            continue
        result = engine.optimize(OptimizationJob(source_path=path))
        if result.status == JobStatus.OPTIMIZED:
            print(
                f"optimized {path.name}: "
                f"{human_size(result.original_size)} -> {human_size(result.new_size)} "
                f"(saved {human_size(result.saved_bytes)}, undo id {result.backup_id})"
            )
            history.record(
                "file",
                path.name,
                str(path),
                result.original_size,
                result.new_size,
                result.backup_id,
            )
        elif result.status == JobStatus.ERROR:
            print(f"error {path.name}: {result.message}", file=sys.stderr)
            exit_code = 1
            continue
        else:
            print(f"{result.status.value} {path.name}: {result.message}")
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
        mark = "↩" if e.undoable else " "  # ↩ marks an undoable row
        line = (
            f"{mark} {e.kind:9} {e.name:24.24} "
            f"{human_size(e.original_size)} -> {human_size(e.new_size)} "
            f"(saved {human_size(e.saved_bytes)})"
        )
        if e.undone:
            line += " [undone]"
        print(line)
    return 0


def _cmd_daemon(_args) -> int:
    from .daemon import run_daemon  # lazy: keeps Qt out of the headless CLI import path

    return run_daemon()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clop-kde")
    sub = parser.add_subparsers(dest="command", required=True)

    p_opt = sub.add_parser("optimize", help="optimize one or more files")
    p_opt.add_argument("files", nargs="+")
    p_opt.set_defaults(func=_cmd_optimize)

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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
