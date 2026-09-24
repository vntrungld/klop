# Klop — In-Progress Indicator Design Spec

**Date:** 2026-07-13
**Status:** Approved (design), pending implementation plan
**Builds on:** M1 (queue), M2 (clipboard), M3 (overlay/router). A feature addition, not a milestone.

## Summary

Show the user that an image is currently being optimized. The floating overlay gains a
**pending state** — a "Optimizing <name>…" card with an **indeterminate** progress bar —
shown for every job (file, drop, and clipboard) the moment it starts, then replaced by the
result (file/drop) or dismissed (clipboard, whose result is a notification).

## Constraint / honest scope

`pngquant`/`jpegoptim` are one-shot subprocesses that emit no progress, so the bar is
**indeterminate** (a busy animation), not a filling percentage. A real percentage becomes
possible in M6 when `ffmpeg` (video) lands and reports progress; the pending state is built so
that upgrade is additive (swap the indeterminate bar for a determinate one driven by a
percentage signal).

## Goals

- When any optimization job starts, show a pending overlay card (thumbnail + "Optimizing <name>…"
  + indeterminate bar, action buttons hidden).
- File/drop: the pending card is replaced by the result card (savings + Undo/Open/drag-out) on
  OPTIMIZED, and dismissed on ERROR/UNCHANGED/SKIPPED (so it never lingers).
- Clipboard: the pending card is transient — dismissed when the job finishes (either outcome);
  the result still surfaces as the existing desktop notification.
- Reuse the existing overlay/router/queue/clipboard units; keep the headless CLI Qt-free.

## Non-Goals

- No real percentage for image tools (they report none). No per-optimizer progress parsing.
- No change to the clipboard result surface (still a notification) or the file/drop result card.
- No new config, no new dependencies.

## Architecture / data flow

```
File/drop:  queue.job_started(path) ──▶ router.on_job_started(path) ──▶ overlay.show_pending(name, thumb)
Clipboard:  watcher.started(png_bytes) ─────────────────────────────▶ overlay.show_pending("Clipboard image", thumb)

File/drop:  queue.job_done(result) ──▶ router.on_job_done(result):
                OPTIMIZED → tray.record_saved + overlay.show_result(result)   # pending → result
                ERROR     → notifier.notify_result(result) + overlay.dismiss
                UNCHANGED/SKIPPED → overlay.dismiss
Clipboard:  watcher.finished ──▶ overlay.dismiss                              # transient card gone
            watcher.optimized(result) ──▶ notifier.notify(...) + tray.record_saved   # unchanged from M2
```

Correctness point: since a pending card is shown for *every* job, the router dismisses it on
the non-OPTIMIZED outcomes, and the clipboard `finished` signal fires on *both* outcomes — the
pending card can never linger.

## Components

### `queue.py` (OptimizationQueue)

- Add `job_started = Signal(object)` (payload: the source `Path`).
- In `_JobRunnable.run()`, emit `job_started` (with the path) BEFORE calling `optimize_fn`, then
  emit `job_done` after. Emitted from the worker thread; Qt queues both to the GUI thread.

### `clipboard.py` (ClipboardWatcher)

- Add `started = Signal(object)` (payload: the original PNG bytes, for the thumbnail) and
  `finished = Signal()`.
- Emit `started` in `_on_changed` right before `self._pool.start(...)` (GUI thread).
- Emit `finished` at the end of `_on_result_ready` (GUI thread), for BOTH the optimized and
  the None (no-gain) outcomes. `optimized` continues to fire only on a real result (unchanged).

### `overlay.py` (ResultOverlay)

- Add a `progress_bar: QProgressBar` to the layout (created with `setRange(0, 0)` for the
  indeterminate/busy animation), hidden by default.
- Add `show_pending(self, title: str, thumbnail: QPixmap | None = None) -> None`:
  - set `title_label` to `f"Optimizing {title}…"`; set the thumbnail (or a themed fallback);
  - clear `savings_label`; show `progress_bar`; hide `undo_button` and `open_button`;
  - position + `show()`/`raise_()`; do NOT start the auto-dismiss timer (a pending card stays
    until the result replaces it or it is dismissed).
- `show_result` (existing) additionally: hide `progress_bar`, show `undo_button`/`open_button`
  (restore from the pending state) before its existing behavior (savings text + dismiss timer).
- `dismiss` (existing) is reused to remove a pending card.

### `results.py` (ResultRouter)

- Add `on_job_started(self, path) -> None` → `overlay.show_pending(Path(path).name, <thumbnail
  from path>)`. (The router loads the file thumbnail; a null/failed load falls back inside the
  overlay.)
- `on_job_done` (existing) gains: ERROR and UNCHANGED and SKIPPED all call `overlay.dismiss()`
  (OPTIMIZED still calls `overlay.show_result`, which itself replaces the pending card).

### `daemon.py` (wiring)

- Connect `queue.job_started → router.on_job_started`.
- Connect `watcher.started → (bytes) overlay.show_pending("Clipboard image", <thumb from bytes>)`
  and `watcher.finished → overlay.dismiss`.

## Error handling

- A pending card with a null/failed thumbnail uses the themed fallback (same as `show_result`).
- If a job never completes (a hung optimizer), the pending card stays until the next job's
  pending/result replaces it — acceptable; optimizer subprocesses are bounded and the worker
  pool drains on quit.
- Concurrency: the file queue runs up to 2 workers; the single-latest overlay shows the most
  recent pending/result (as it already does for results). Clipboard is serial (max-1 pool).

## Testing strategy

- **queue.py:** a fake `optimize_fn` records call order; assert `job_started(path)` is emitted
  before `job_done`, and both arrive on the GUI thread (drive with `wait_for_done` +
  `processEvents`).
- **overlay.py:** `show_pending("photo.png")` sets the title to include "Optimizing", shows the
  `progress_bar` (visible, range 0–0) and hides `undo_button`/`open_button`; a subsequent
  `show_result` hides the bar and shows the buttons with the savings text.
- **clipboard.py:** feed a synthetic image; assert `started` fires (with the bytes) before the
  worker result and `finished` fires after — for both a smaller-result and a None-result
  `optimize_fn`.
- **results.py:** `on_job_started(path)` calls `overlay.show_pending` with the filename; a fake
  ERROR/UNCHANGED/SKIPPED `on_job_done` calls `overlay.dismiss` (and OPTIMIZED calls
  `show_result`, not dismiss).
- **daemon.py:** emitting `queue.job_started`/`watcher.started`/`watcher.finished` drives the
  overlay's pending/dismiss (verified via a fake overlay recording the calls).
- **Manual smoke (real session):** pick/drop a file and copy an image; confirm the "Optimizing…"
  card with the busy bar appears, then the file result card / the clipboard card vanishing with
  the notification.

## Dependencies

None new. `QProgressBar` is part of PySide6 QtWidgets already in use.
