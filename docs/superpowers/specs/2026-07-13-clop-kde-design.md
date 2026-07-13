# Clop-KDE — Design Spec

**Date:** 2026-07-13
**Status:** Approved (design), pending implementation plan

## Summary

Clop-KDE is a background media-optimization utility for KDE Plasma 6, inspired by
[Clop](https://github.com/FuzzyIdeas/Clop) on macOS. It transparently optimizes
images, video, and PDFs — "copy large, paste small, send fast." Optimization is
triggered from four input sources (clipboard, watched folders, drag-and-drop,
Dolphin/hotkey), all feeding a single optimization engine that shells out to
open-source optimizer CLIs.

## Goals

- Auto-optimize images copied to the clipboard, replacing clipboard contents in place.
- Auto-optimize new files landing in watched folders.
- Optimize files on demand via a drop-target window, Dolphin context menu, or global hotkey.
- Show an animated floating overlay with per-job savings and quick actions (undo, open, drag-out, downscale).
- Never destroy data: back up originals before replacing, and support undo.
- Degrade gracefully based on which optimizer CLIs are installed.

## Non-Goals

- No cloud upload / sharing integrations (Clop's "upload" features).
- No macOS Shortcuts-equivalent scripting engine in the MVP.
- No custom image codecs — we orchestrate existing CLI tools, not reimplement them.

## Stack Decision

**Python 3 + PySide6 (Qt6) daemon, with a QML floating overlay.**

Rationale:
- The app is fundamentally a **subprocess orchestrator** — the real work happens in
  external CLIs (pngquant, jpegoptim, ffmpeg, ghostscript, `vips`), so daemon language
  speed is irrelevant and Python's iteration speed wins.
- PySide6 exposes the full Qt6 API needed by all four sources: `QSystemTrayIcon`
  (StatusNotifierItem), `QClipboard`, `QFileSystemWatcher`, `QProcess`, and **QML** for
  the animated floating thumbnail.
- KDE integration needs no C++: Dolphin service menus are `.desktop` files that call any
  executable; global shortcuts register over D-Bus (KGlobalAccel); notifications via
  `QSystemTrayIcon` / `notify-send`.
- Prior Python + Plasma 6 experience in this workspace (claude-status-bar-kde) lowers risk.

C++/KF6 would be the "purest" KDE citizen but is heavy boilerplate for a solo project;
Rust-Qt bindings are still too immature.

## Architecture

All four triggers are **input sources** that feed one central engine.

```
┌─────────── Input Sources ───────────┐
│ ClipboardWatcher  FolderWatcher      │
│ DropTargetWindow  CLI/ServiceMenu    │
└──────────────┬───────────────────────┘
               ▼
        OptimizationQueue  ──►  Engine (picks optimizer per filetype)
               │                    │ subprocess: pngquant/ffmpeg/gs/vips
               ▼                    ▼
     Tray (StatusNotifier)    FloatingOverlay (QML)
                                 └─ downscale / drag-out / undo / open
               ▼
        BackupStore (undo)
```

Each source and the engine are independent units with narrow interfaces, so they can be
built and tested one at a time and sources can be added incrementally.

### Units and responsibilities

- **Engine** — accepts an `OptimizationJob`, selects the optimizer, runs it via `QProcess`,
  enforces safety rules, emits results. Depends on: `BackupStore`, optimizer capability map.
- **OptimizationQueue** — async queue with a small worker pool (default 2 concurrent) so a
  large video doesn't block image jobs.
- **BackupStore** — copies originals before replacement; supports undo; prunes by age/size.
- **Input sources** — each produces `OptimizationJob`s and knows nothing about the engine's
  internals:
  - `ClipboardWatcher`, `FolderWatcher`, `DropTargetWindow`, `CLI/ServiceMenu` entrypoint.
- **Tray** — `QSystemTrayIcon` showing running "saved X MB" total, enable/disable, quit, open-config.
- **FloatingOverlay** — QML window showing the result thumbnail, savings, and quick actions.

## The Optimization Engine

### Job model

A source produces an `OptimizationJob`:
`{ source_path OR clipboard_image, media_type, trigger, options }`.
Jobs enter the `Queue` and are processed by the worker pool.

### Filetype → optimizer mapping

All optimizers are optional and detected at startup (capability map). A media type with no
available optimizer is skipped with a clear log/notification.

| Media | Detected by | Primary tool | Fallback / notes |
|---|---|---|---|
| PNG | magic bytes / ext | `pngquant` (lossy, default) | `oxipng` for lossless mode; skip if neither present |
| JPEG | magic bytes / ext | `jpegoptim` | `--max=N` quality knob |
| GIF | magic bytes / ext | `gifsicle -O3` | `gifski` for higher quality |
| WebP | magic bytes / ext | `cwebp` | |
| HEIC/HEIF | magic bytes / ext | `vips` → JPEG/PNG (convert) | Clop-style auto-convert |
| Video (mp4/mov/mkv…) | magic bytes / ext | `ffmpeg` (H.264/265) | MOV→MP4 convert |
| PDF | magic bytes / ext | `ghostscript` (`-dPDFSETTINGS`) | |

### Resize / downscale

A job may carry a `scale` (e.g. 0.5) or a target longest-edge:
- Images → `vips resize`.
- Video → `ffmpeg -vf scale`.

This backs the overlay's downscale buttons (0.5×, 1–9 presets).

### Safety and undo

- Before writing, the original is copied to `BackupStore`
  (`~/.local/share/clop-kde/backups/<hash>/`).
- Optimize writes to a temp file and **only replaces the original if the result is actually
  smaller**; otherwise the original is kept and the job reports "already optimal."
- **Undo restores from backup.**
- Backups pruned by age/size (configurable; default 7 days / 500 MB).
- Default write mode is **in-place replacement + backup/undo**, not `*-optimized` copies.

### Clipboard case

Clipboard image → write to temp PNG → optimize → load result back into `QClipboard`.
Text and file-path clipboard entries are ignored. Guard against re-optimizing our own
output via a content hash / marker.

### Result signal

Engine emits `job_done(original_size, new_size, path, backup_id)`:
- Tray updates a running "saved X MB" total.
- Overlay shows the thumbnail + savings.
- Desktop notification fires.

### Configuration

Single `~/.config/clop-kde/config.toml`:
- enabled sources
- watched folders (+ per-folder rules)
- per-type quality
- concurrency
- backup retention
- "min bytes saved to bother" threshold

## MVP Build Order

Each milestone is independently useful and testable.

**M0 — Skeleton + Engine core.**
Project scaffold, `config.toml` loader, optimizer capability detection, `Engine` + `Queue`
+ `BackupStore` with the PNG/JPEG path, and a `clop-kde optimize <file>` CLI entrypoint that
exercises the whole engine with no UI. Tests: smaller-or-unchanged, backup + undo.

**M1 — Tray + notifications.**
`QSystemTrayIcon` (StatusNotifierItem) with running "saved X MB" total, enable/disable, quit,
open-config. Desktop notification on job done. Now a real background daemon.

**M2 — Clipboard auto-optimize** (signature feature).
`ClipboardWatcher` → temp file → engine → write result back to clipboard. Guard against
re-optimizing our own output.

**M3 — Floating overlay + drop target (QML).**
Animated floating thumbnail on completion: savings + buttons for undo / open / drag-out,
auto-dismiss timer. Add downscale (0.5×, 1–9 presets) wired to the engine's resize path.
Includes the `DropTargetWindow` source: a small always-available window (toggled from the
tray) that accepts dragged-in files and enqueues them — the manual drag-and-drop trigger.

**M4 — Watched folders.**
`FolderWatcher` (`QFileSystemWatcher` + debounce) on configured dirs; ignore backups/temp;
per-folder rules.

**M5 — Dolphin service menu + global hotkey.**
`.desktop` service menu ("Optimize with Clop") reusing the M0 CLI; global shortcut via
KGlobalAccel/D-Bus to optimize clipboard or current selection.

**M6 — Video + PDF + HEIC convert.**
Add `ffmpeg` / `ghostscript` / `vips`-convert optimizers and format conversion. Deferred
because they are heavier; the framework already handles them once the mapping exists.

**M7 — Packaging.**
systemd `--user` service for autostart, install script, dependency doc; optional Flatpak later.

Key property: **M0's CLI entrypoint doubles as M5's service-menu backend**, and every source
from M2/M4/M5 feeds the same M0 engine — so no rework.

## Dependencies (external CLIs, all optional/detected)

`pngquant` (default PNG), `oxipng` (lossless PNG option), `jpegoptim`, `gifsicle`, `gifski`, `cwebp`, `libvips` (`vips`),
`ffmpeg`, `ghostscript` (`gs`). Runtime: Python 3, PySide6, KDE Plasma 6 (Qt6/KF6).

## Testing Strategy

- Engine tested headless via the CLI entrypoint against sample fixtures (asserting
  smaller-or-unchanged output, backup creation, and undo restoration).
- Capability detection tested by stubbing `PATH`.
- Sources tested by injecting synthetic jobs / temp files; UI kept thin so most logic is
  testable without a running Plasma session.
