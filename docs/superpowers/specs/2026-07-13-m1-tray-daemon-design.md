# Klop M1 — Tray Daemon + Notifications Design Spec

**Date:** 2026-07-13
**Status:** Approved (design), pending implementation plan
**Builds on:** M0 (headless engine core) — see `2026-07-13-klop-design.md`

## Summary

M1 turns Klop from a headless CLI into a real background **daemon** with a KDE
system-tray presence. It adds a Qt event loop, a system-tray icon and menu, an
off-GUI-thread optimization queue, and desktop notifications with an inline **Undo**
action. It reuses the entire M0 engine unchanged — M1 is orchestration and UI around
M0, not new optimization logic.

Because no automatic input source exists yet (clipboard is M2, watched folders M4),
M1's manual entry point is a tray **"Optimize files…"** action that opens a file picker
and enqueues the chosen files. This makes M1 independently demoable and testable.

## Goals

- Launch a long-lived daemon via `klop daemon` that shows a system-tray icon.
- Tray menu: **Optimize files…**, a running **Saved: X** total, an **Enabled** toggle,
  **Open config**, and **Quit**.
- Run optimization jobs off the GUI thread via a worker pool, keeping the UI responsive.
- Show a desktop notification per optimized file with savings and an **Undo** button that
  restores the original via the M0 backup.
- Keep the existing headless CLI (`optimize` / `undo` / `caps`) working and unchanged.

## Non-Goals

- No clipboard watching (M2), watched folders (M4), Dolphin menu / global hotkey (M5),
  floating overlay (M3), or video/PDF/HEIC optimizers (M6).
- No IPC between the CLI and the daemon — the tray file picker is the M1 entry point.
- No persistence of the running "saved" total across restarts (session-only in M1).
- No autostart / systemd unit (M7 packaging).

## Stack

- **PySide6 (Qt6)** — new dependency, added to `pyproject.toml`. Only the daemon code path
  imports Qt; the M0 modules stay pure-Python and importable without PySide6.
- Desktop notifications via **QtDBus** to `org.freedesktop.Notifications` (chosen because it
  supports action buttons and the `ActionInvoked` signal, and fits inside the Qt event loop;
  `notify-send` cannot easily capture the button click and KNotifications lacks clean PySide6
  bindings).

## Architecture

```
klop daemon
  └─ QApplication (Qt event loop)
       ├─ TrayApp (QSystemTrayIcon + QMenu)          app.py
       │    "Optimize files…" → QFileDialog → queue.submit(paths)
       │    job_done(result) → update "Saved: X" + notifier.notify_result(result)
       ├─ OptimizationQueue (QThreadPool)             queue.py
       │    wraps the M0 Engine; runs each job in a worker thread;
       │    emits job_done(JobResult) delivered on the GUI thread
       └─ Notifier (QtDBus backend)                   notifier.py
            desktop notification per job;
            "Undo" action → engine.undo(backup_id)

Reused unchanged from M0: Engine, BackupStore, optimizer registry, config, media, job.
```

Each unit has one responsibility and a narrow, injectable interface so it can be tested
without a live Plasma session.

## Components

### `daemon` subcommand (in `cli.py`)

Adds a `daemon` subparser that constructs a `QApplication`, builds the Engine (as
`_build_engine()` already does), the `OptimizationQueue`, the `Notifier`, and the `TrayApp`,
then runs the event loop. The existing `optimize` / `undo` / `caps` subcommands are unchanged
and remain fully headless (no Qt import unless `daemon` is invoked).

### OptimizationQueue (`queue.py`)

- `OptimizationQueue(QObject)` constructed with an `optimize_fn` (defaults to
  `engine.optimize`) and `concurrency: int` (from `Config.concurrency`, default 2).
- Holds a `QThreadPool` with `setMaxThreadCount(concurrency)`.
- `submit(paths: list[Path])` — for each path, enqueue a `QRunnable` that calls
  `optimize_fn(OptimizationJob(source_path=path))`.
- On job completion, **emits `job_done(JobResult)`**. The receiver (TrayApp) lives on the GUI
  thread, so Qt's queued connection delivers the result on the GUI thread — no manual locking.
- Any unexpected exception inside a worker is caught and emitted as a synthesized
  `JobResult(status=ERROR, …)`, so the UI has a single uniform handler.

Rationale for QThreadPool over `ThreadPoolExecutor` or async `QProcess`: it is idiomatic Qt,
integrates with the event loop, and reuses M0's blocking engine untouched.

### Notifier (`notifier.py`)

- `Notifier(QObject)` constructed with a **backend** and an `undo_fn` (defaults to
  `engine.undo`). The backend interface isolates D-Bus:
  - `send(summary: str, body: str, actions: list[tuple[str, str]], icon: str) -> int`
    returns a notification id.
  - fires an `on_action(notification_id: int, action_key: str)` callback when a button is
    clicked, and `on_closed(notification_id)` when dismissed.
- Real backend = a thin QtDBus adapter over `org.freedesktop.Notifications`
  (`Notify` method; `ActionInvoked` / `NotificationClosed` signals). Fake backend (tests)
  records `send` calls and can fire `on_action` / `on_closed`.
- `notify_result(result: JobResult)`:
  - `OPTIMIZED` with a `backup_id` → `send` with body `"<name>  A → B (-N%)"` and an
    `("undo", "Undo")` action; record `notification_id → backup_id`.
  - `ERROR` → `send` a warning notification, no action.
  - `UNCHANGED` / `SKIPPED` → no notification (avoid spam).
- On `on_action(id, "undo")` for a known id: call `undo_fn(backup_id)`, then `send` a
  "Restored <name>" follow-up. Unknown ids and other action keys are no-ops. `on_closed`
  removes the id from the map.

### TrayApp (`app.py`)

- Builds a `QSystemTrayIcon` with a `QMenu`:
  - **Optimize files…** — opens a file picker (via an injectable `pick_files` callable so
    tests avoid a real dialog) and calls `queue.submit(paths)`. Disabled when **Enabled** is off.
  - **Saved: X** — a disabled info action; its text updates on each `job_done` (session total
    of `saved_bytes` for `OPTIMIZED` results, formatted via `format.human_size`).
  - **Enabled** — checkable, default on; gates whether new jobs are accepted (this state is
    what M2's clipboard auto-optimize will consult).
  - **Open config** — `xdg-open` the config path, creating it with defaults if missing.
  - **Quit** — quits the application.
- Connects `queue.job_done` → an on-GUI-thread handler that updates the total and calls
  `notifier.notify_result`.

### Shared formatting (`format.py`)

- Extract M0's `_human` byte formatter from `cli.py` into `format.human_size(n: int) -> str`
  so both `cli.py` and `notifier.py` use one implementation. Add `percent_saved(old, new)`
  for the notification body. `cli.py` imports from here (behavior unchanged).

### Tray icon asset

- A simple bundled SVG icon shipped in the package (e.g. `klop/assets/tray.svg`), loaded
  via `QIcon`, with a themed-icon fallback (`QIcon.fromTheme("image-x-generic")`) if the asset
  is missing.

## Error Handling

- Worker exceptions → synthesized `ERROR` JobResult (never crash the pool).
- `ERROR` results surface as warning notifications; the daemon keeps running.
- `Open config` creating the file: if the config dir/file cannot be created, show a warning
  notification rather than crashing.
- If the session bus / notification service is unavailable, `Notifier` degrades to no-ops
  (logs a warning); optimization still proceeds and the tray total still updates.

## Testing Strategy

- **queue.py:** `QCoreApplication` + a fake `optimize_fn`; submit paths, pump the event loop
  until `job_done` signals arrive; assert results, and that a raising `optimize_fn` yields a
  synthesized `ERROR` result.
- **notifier.py:** fake backend — assert the `undo` action is attached only for
  `OPTIMIZED`+`backup_id`; the `id → backup_id` map is correct; `undo_fn` is dispatched on the
  right action with the right id; unknown ids / other keys are no-ops; `UNCHANGED`/`SKIPPED`
  send nothing. No real D-Bus.
- **format.py:** pure unit tests for `human_size` (including the previously-fixed KB/MB/GB
  cases) and `percent_saved`.
- **app.py:** under `QT_QPA_PLATFORM=offscreen`, construct `TrayApp` with a fake queue and an
  injected `pick_files`; assert "Optimize files…" calls `queue.submit` with the picked paths;
  a fake `job_done` updates the "Saved:" text; toggling **Enabled** disables the picker.
  Parts requiring a real system tray are `skipif`-guarded on `QSystemTrayIcon.isSystemTrayAvailable()`.
- **Manual smoke:** `klop daemon`, pick a JPEG, confirm the notification appears and
  **Undo** restores the original.

## Dependencies

Runtime adds **PySide6** (Qt6). Notifications need a running session D-Bus with an
`org.freedesktop.Notifications` service (any Plasma session). External optimizer CLIs are the
same optional set as M0 (pngquant/jpegoptim for the shipped types).
