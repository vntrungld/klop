# Clop-KDE M2 — Clipboard Auto-Optimize Design Spec

**Date:** 2026-07-13
**Status:** Approved (design), pending implementation plan
**Builds on:** M0 (engine) and M1 (tray daemon) — see their specs in this folder.

## Summary

M2 adds Clop's signature feature: when a **bitmap image** is copied to the clipboard,
the daemon transparently optimizes it and puts the smaller image back — "copy large,
paste small." A desktop notification reports the savings and offers **Undo**, which
restores the original image to the clipboard. Optimization runs off the GUI thread and
is gated by the existing tray **Enabled** toggle.

## Goals

- Watch the clipboard; when it holds raw image data, optimize it (PNG via pngquant) and
  write the smaller result back so a subsequent paste delivers the optimized bytes.
- Never re-optimize our own output or an already-optimized image (content-hash guard).
- Show a notification with savings and an **Undo** action that restores the original image
  to the clipboard.
- Run the optimizer off the GUI thread; keep clipboard reads/writes on the GUI thread.
- Gate watching by the tray **Enabled** toggle and a `clipboard_watch` config flag.
- Reuse the M0 optimizer registry and M1 tray/notifier; leave the M0 engine unchanged.

## Non-Goals

- No handling of copied image **files** (`text/uri-list`) — that is the Dolphin menu (M5)
  and watched folders (M4). M2 is raw bitmap image data only.
- No video/PDF/HEIC clipboard handling; no format conversion. PNG bitmap only in M2.
- No persistence of clipboard-undo across daemon restarts (in-memory, session-scoped).

## Stack

Reuses PySide6 (Qt6) from M1: `QClipboard` (`QGuiApplication.clipboard()`), `QMimeData`,
`QImage`/`QBuffer`, `QThreadPool`. Optimization shells out to `pngquant` via the M0
optimizer registry. No new dependencies.

## Architecture

```
QClipboard.dataChanged  (daemon, GUI thread)
   │  Enabled toggle on?  AND clipboard has image data?
   │  read image/png bytes; hash them
   │  hash in bounded "seen" LRU?  ── yes ──▶ ignore (our own output / already optimized)
   ▼ no
  worker thread: optimize_image_bytes(png_bytes)  →  smaller bytes | None
   ▼ back on GUI thread (None → stop, no change)
  stash original bytes (undo)
  write optimized image/png bytes back to clipboard via QMimeData
  add original AND optimized hashes to the "seen" LRU
   ▼
  notification "Clipboard image  A → B (-N%)  [Undo]"  +  tray.record_saved(saved)

Reused unchanged: M0 Engine/BackupStore/optimizer registry; M1 TrayApp/queue.
Generalized: M1 Notifier undo (backup_id-specific → per-notification callback).
```

## Components

### `clipboard.py`

- `image_to_png_bytes(image: QImage) -> bytes` — serialize a QImage to PNG bytes (QBuffer).
- `content_hash(png_bytes: bytes) -> str` — sha1 hex of the PNG bytes (loop-prevention key).
- `optimize_image_bytes(png_bytes, config, capabilities, runner=None) -> bytes | None` —
  write bytes to a temp PNG, select the PNG optimizer (`select_optimizer(MediaType.PNG, …)`),
  run it via an injectable `runner` (same pattern as the engine) into a temp output, and
  return the optimized bytes **only if smaller** by at least `config.min_bytes_saved`, else
  `None`. No file backup (there is no persistent original file). If no optimizer is available,
  returns `None`.
- `ClipboardWatcher(QObject)` — owns the loop-prevention set and the worker offload:
  - Constructed with `clipboard`, `optimize_fn` (defaults to a closure over
    `optimize_image_bytes` + config/capabilities), a `QThreadPool` (max 1), and an
    `enabled: bool` property (default True).
  - Connects `clipboard.dataChanged` → `_on_clipboard_changed` (GUI thread): if disabled or
    no image, return; read `image/png` bytes (or serialize the QImage if only an image is
    present); compute the hash; if in the `seen` LRU, return; otherwise offload
    `optimize_fn(bytes)` to the worker.
  - On worker completion (delivered on the GUI thread via a signal): if `None`, done; else
    stash the original bytes keyed by an id, write the optimized bytes back to the clipboard
    (`_set_clipboard_png(optimized)`), add both hashes to the `seen` LRU, and emit
    `optimized(ClipboardResult)`.
  - `undo(token)` — restore the stashed original bytes to the clipboard.
  - `_seen` is a bounded LRU (e.g. last 32 hashes) to bound memory.
- `ClipboardResult` — small dataclass: `original_size: int`, `new_size: int`,
  `undo_token: str`; property `saved_bytes = max(0, original_size - new_size)`.

### `notifier.py` (generalized undo)

- New core method `notify(summary, body, *, undo: Callable[[], None] | None = None,
  undo_confirm: str | None = None, icon: str = "") -> int` — sends a notification; if `undo`
  is provided, attaches the `("undo","Undo")` action and stores
  `notification_id → (undo, undo_confirm)`. On `ActionInvoked "undo"` for a known id, calls the
  stored callback, removes the id, and (if `undo_confirm` is set) sends `undo_confirm` as a
  follow-up notification. `on_closed` forgets the id. `undo_confirm` keeps the post-undo
  confirmation text caller-controlled so both file- and clipboard-undo read naturally.
- `notify_result(result: JobResult)` becomes a thin wrapper: for `OPTIMIZED` with a
  `backup_id` it calls `notify(name, body, undo=lambda: self._undo_fn(result.backup_id),
  undo_confirm=f"Restored {name}")`; for `ERROR`, `notify(name, warning)`;
  `UNCHANGED`/`SKIPPED` silent. **M1 behavior (including the "Restored <name>" follow-up) is
  preserved.** The internal `notification_id → (backup_id, name)` map is replaced by
  `notification_id → (callback, undo_confirm)`; existing M1 undo tests are updated to assert
  the callback is invoked (still using the fake backend).

### `app.py` (tray)

- Extract the session-total update into a public `record_saved(saved_bytes: int) -> None`
  that increments the total and updates the `Saved: X` action text. `_on_job_done` calls
  `record_saved(result.saved_bytes)` for `OPTIMIZED` results. The clipboard path calls
  `record_saved` too, so both feed one total.
- The **Enabled** toggle additionally sets `clipboard_watcher.enabled` (wired in the daemon),
  so turning it off pauses clipboard watching.

### `config.py`

- Add `clipboard_watch: bool = True`. When false, the daemon does not start the watcher.

### `daemon.py` (wiring)

- `build_daemon` constructs a `ClipboardWatcher` over `QGuiApplication.clipboard()` (when
  `config.clipboard_watch`), wires its `optimized` signal → `tray.record_saved(...)` +
  `notifier.notify(..., undo=lambda: watcher.undo(token), undo_confirm="Restored image to clipboard")`,
  and connects the tray **Enabled** toggle to `watcher.enabled`. Injectable
  `clipboard`/`optimize_fn` keep it testable.

## Error Handling

- No optimizer available, or result not smaller → `optimize_image_bytes` returns `None`; the
  clipboard is left untouched, no notification (silent, avoids churn).
- Worker exceptions are caught and treated as `None` (no change), never crash the pool.
- Non-image clipboard changes (text, uri-list) are ignored.
- Writing to the clipboard while unfocused can fail on some compositors; failures are logged
  and swallowed (the optimization simply doesn't take effect that time).

## Testing Strategy

- `optimize_image_bytes`: injected fake runner producing smaller / larger / equal output →
  assert optimized bytes vs `None`; real-pngquant path gated on `shutil.which`.
- Loop-prevention: drive `ClipboardWatcher`'s change handler with a synthetic image and an
  injected `optimize_fn`; assert it optimizes once, that feeding back the optimized hash is
  skipped, and that re-feeding an already-seen hash is a no-op; assert the LRU is bounded.
- Undo generalization (`notifier.py`): fake backend — `notify(..., undo=cb)` then fire the
  action → assert `cb` ran and the id is forgotten; unknown id / non-"undo" key → no-op;
  `notify_result` still dispatches the file-undo callback (M1 tests updated, stay green).
- `ClipboardWatcher` under offscreen `qapp` with a fake clipboard + injected `optimize_fn`:
  assert enabled-gating (disabled → no optimize), write-back sets the optimized bytes, and
  `undo(token)` restores the original bytes.
- `record_saved`: assert both a file `job_done` and a clipboard result accumulate one total.
- Manual smoke (interactive KDE session): copy a screenshot, confirm the notification with
  savings appears, that a paste yields a smaller image, and that **Undo** restores the original.

## Dependencies

No new runtime dependencies beyond M1 (PySide6 + `gdbus` for notifications). `pngquant`
remains the optional optimizer for the clipboard PNG path.
