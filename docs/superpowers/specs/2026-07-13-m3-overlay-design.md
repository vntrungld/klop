# Klop M3 — Floating Overlay + Drop Target Design Spec

**Date:** 2026-07-13
**Status:** Approved (design), pending implementation plan
**Builds on:** M0 (engine), M1 (tray daemon), M2 (clipboard) — see their specs in this folder.

## Summary

M3 adds two manual/visual surfaces to the tray daemon: an animated **floating overlay**
that appears when a file is optimized (thumbnail, savings, and quick actions — Undo, Open,
drag-out), and a **drop-target window** for optimizing files by dragging them in. The overlay
replaces the desktop notification for file and drop-target results; clipboard results keep
their notification (they have no file to preview or drag). Downscale presets are deferred to
M6 (when the resize path they need is built); the overlay leaves a slot for them.

## Goals

- Show a floating thumbnail card (QWidget) for OPTIMIZED file/drop results: thumbnail, filename,
  savings, and actions Undo / Open / drag-out; animated in, auto-dismissed, hover-to-persist.
- Provide a drop-target window that enqueues dragged-in files for optimization.
- Route results by source: file/drop → overlay; clipboard → notification (unchanged);
  errors → notification; unchanged/skipped → silent.
- Reuse the M0 engine, M1 queue/notifier/tray, and M2 clipboard unchanged in behavior.
- Everything is a QWidget under the one QApplication and testable headlessly (offscreen).

## Non-Goals

- No downscale/resize (deferred to M6; the overlay reserves a button-row slot for it).
- No QML/Qt Quick — QWidget only, for codebase consistency and headless testability.
- No multi-card stack — a single overlay shows the latest result (a stack is a later refinement).
- No overlay for clipboard results — those keep their desktop notification.

## Stack

Reuses PySide6 (Qt6) QtWidgets/QtGui/QtCore: `QWidget`, `QLabel`, `QPushButton`,
`QPropertyAnimation`, `QTimer`, `QDrag`, `QMimeData`, `QPixmap`, `QScreen`. No new dependencies.

## Architecture

```
 queue.job_done  ──▶  ResultRouter.on_job_done(result)
 (file picker &            OPTIMIZED → tray.record_saved(saved) + overlay.show_result(result)
  drop target)             ERROR     → notifier.notify_result(result)  (M1 warning path)
                           UNCHANGED / SKIPPED → silent

 clipboard.optimized ──▶ notifier.notify(...)          (unchanged from M2)

 New QWidget components:
   ResultOverlay    (overlay.py)    — frameless translucent card; thumbnail + savings +
                                      [Undo] [Open] [drag-out]; slide/fade + auto-dismiss
   DropTargetWindow (droptarget.py) — always-on-top drop window → queue.submit(paths);
                                      toggled from a new tray "Show drop target" action
   ResultRouter     (results.py)    — routes job_done across tray/overlay/notifier

 Refactor: TrayApp no longer connects queue.job_done (that moves to the daemon → ResultRouter).
 TrayApp keeps record_saved, the picker's queue.submit, and gains the drop-target toggle action.
```

## Components

### `overlay.py` — `ResultOverlay`

- `ResultOverlay(undo_fn, open_fn=<xdg-open>, parent=None)` — a `QWidget` with window flags
  `FramelessWindowHint | WindowStaysOnTopHint | Tool` and `WA_TranslucentBackground`.
  - `undo_fn(backup_id) -> object` — injected (defaults to nothing in tests; daemon passes
    `engine.undo`). `open_fn(path)` — injected (defaults to `xdg-open` via subprocess), so tests
    don't launch a real app.
- `show_result(result: JobResult) -> None` — populate the card from `result`:
  - thumbnail: `QPixmap(str(result.path))` scaled to ~96px (`Qt.KeepAspectRatio`,
    `Qt.SmoothTransformation`); a themed fallback icon if the pixmap is null.
  - filename `result.path.name`; savings `f"{human_size(orig)} → {human_size(new)}
    (-{percent_saved(orig,new)}%)"`.
  - remember `result.backup_id` and `result.path` for the actions.
  - position bottom-right of the primary screen (`QGuiApplication.primaryScreen().availableGeometry()`
    with a margin), animate in (`QPropertyAnimation` on `windowOpacity` and/or geometry), start the
    auto-dismiss `QTimer` (~4000 ms), and `show()`.
- Actions:
  - **Undo** button → `undo_fn(backup_id)` then `dismiss()`.
  - **Open** button → `open_fn(path)` (guarded: `try/except OSError`).
  - **drag-out** → the thumbnail label is a drag source; `mouseMoveEvent` past the drag
    threshold starts `QDrag` with `_drag_mime(path)` (a `QMimeData` whose `urls` is
    `[QUrl.fromLocalFile(str(path))]`, i.e. `text/uri-list`). `_drag_mime` is a standalone helper
    so the mime construction is unit-tested without executing a modal drag.
- Lifecycle: `enterEvent` stops the dismiss timer; `leaveEvent` restarts it; `dismiss()` runs the
  fade-out animation then `hide()`. A new `show_result` while visible updates the card and resets
  the timer (single-overlay-latest).
- Downscale slot: the button row is built so future downscale buttons can be appended (M6); none
  are added in M3.

### `droptarget.py` — `DropTargetWindow`

- `DropTargetWindow(submit_fn, parent=None)` — an always-on-top `QWidget` (`WindowStaysOnTopHint |
  Tool`) with `setAcceptDrops(True)` and a "Drop images to optimize" label.
  - `dragEnterEvent`: accept if the mime `hasUrls()`.
  - `dropEvent`: extract local file paths via `_urls_to_paths(mime) -> list[Path]`
    (`[Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]`); if non-empty, call
    `submit_fn(paths)`. `_urls_to_paths` is a standalone helper, unit-tested directly.
- Toggled visible/hidden by the tray "Show drop target" action.

### `results.py` — `ResultRouter`

- `ResultRouter(tray, overlay, notifier)` — plain object (or QObject) with
  `on_job_done(result: JobResult) -> None`:
  - `OPTIMIZED` → `tray.record_saved(result.saved_bytes)` and `overlay.show_result(result)`.
  - `ERROR` → `notifier.notify_result(result)` (reuses M1's ERROR-warning path; no duplicated
    formatting — `notify_result` on an ERROR sends the warning with no action).
  - `UNCHANGED` / `SKIPPED` → nothing.

### `app.py` (TrayApp) changes

- Remove the `queue.job_done.connect(self._on_job_done)` wiring and the `_on_job_done` method
  (that routing moves to `ResultRouter`, connected by the daemon). Keep `record_saved`, the
  picker (`optimize_action` → `queue.submit`), and the Enabled toggle.
- Add a **"Show drop target"** action that toggles a drop-target window's visibility. TrayApp
  receives the window (or a show/hide callable) via the daemon; a `drop_toggle_fn` injected in the
  constructor keeps it testable.

### `daemon.py` (wiring)

- Construct `ResultOverlay(undo_fn=engine.undo)`, `DropTargetWindow(submit_fn=queue.submit)`, and
  `ResultRouter(tray, overlay, notifier)`; connect `queue.job_done → router.on_job_done`.
- Wire the tray "Show drop target" toggle to show/hide the drop window.
- `build_daemon` now returns a `Daemon` `NamedTuple` (fields: `tray`, `queue`, `notifier`,
  `watcher`, `overlay`, `droptarget`, `router`) instead of a growing bare tuple — the M1/M2 tests
  and `run_daemon` are updated to attribute access. This stops the return arity from being a
  churn point every milestone.

## Error Handling

- A null/failed thumbnail pixmap falls back to a themed icon; never crashes `show_result`.
- **Open** and drag construction guard against `OSError`/invalid paths.
- The overlay only ever receives OPTIMIZED results (which carry a real `path` and `backup_id`);
  ERROR/UNCHANGED/SKIPPED never reach it.
- Toggling the drop target when the window can't be shown (headless) degrades silently.

## Testing Strategy

- **ResultOverlay:** offscreen `qapp`; `show_result` with a real temp PNG → assert the savings and
  filename text and a non-null thumbnail; **Undo** invokes the injected `undo_fn` with the
  backup_id and hides the card; **Open** calls the injected `open_fn` with the path; a null-pixmap
  path falls back without error; `_drag_mime(path)` yields a `QMimeData` whose single URL is the
  file; the auto-dismiss timer hides the widget (drive it by calling the timeout slot directly).
- **DropTargetWindow:** `_urls_to_paths` maps a `QMimeData` of file URLs to local paths and drops
  non-local URLs; simulating a drop (calling the drop handler with such a mime) calls `submit_fn`
  with the paths; an empty/urlless drop calls nothing.
- **ResultRouter:** fake `tray`/`overlay`/`notifier` — OPTIMIZED → overlay.show_result +
  tray.record_saved and **no** notifier call; ERROR → notifier.notify and no overlay; UNCHANGED
  and SKIPPED → nothing anywhere.
- **TrayApp:** the "Show drop target" action calls the injected `drop_toggle_fn`; confirm
  `job_done` is no longer self-handled (the old `_on_job_done` tests are removed / relocated to
  ResultRouter).
- **daemon:** `build_daemon` constructs overlay/droptarget/router; emitting a fake OPTIMIZED
  `job_done` shows the overlay and updates the tray total (not a notification); a fake ERROR
  notifies.
- **Manual smoke (real session):** optimize a file (tray picker) and drop files onto the window;
  confirm the floating card appears with the correct savings, Undo restores the file, Open opens
  it, and the thumbnail can be dragged into another application.

## Dependencies

No new runtime dependencies beyond M1/M2 (PySide6 + `gdbus` for clipboard notifications).
`pngquant`/`jpegoptim` remain the optional optimizers; the overlay thumbnails use Qt's built-in
image loading.
