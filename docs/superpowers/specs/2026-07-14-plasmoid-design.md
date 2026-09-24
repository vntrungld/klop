# Klop — Plasma Applet (Plasmoid) Design Spec

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan
**Sub-project C of the applet direction.** Builds on M0 (engine/backup/CLI), the history
store (Sub-project A: `klop history [--json]`), and the notification work (CLI
`optimize` posts a desktop notification when run without a terminal). Sub-project B (the
headless-daemon/bridge refactor) is *not* required first: the plasmoid drives the backend
entirely through the existing Qt-free CLI.

## Summary

A native Plasma 6 panel applet (`org.trungld.klop`) that is the interactive UI for
Klop: **drag a file onto its panel icon to optimize it**, and **click the icon to see a
popup** with the running "saved" total, a recent-optimizations history list with per-file
Undo, and a Configure button that opens a real form for the optimizer settings.

The plasmoid is a thin QML shell. Every backend operation is a shell-out to the `klop`
CLI — `optimize`, `history --json`, `undo`, and two new `config` subcommands — so no D-Bus
bridge or running daemon is needed, and all real logic stays in the tested, Qt-free Python.
This also sidesteps the floating-window problems on tiling/force-maximize KWin setups: an
applet lives inside plasmashell and is not subject to window rules.

## Motivation

The daemon's floating `DropTargetWindow` (M3) is unusable on the target user's KWin setup: a
global "force maximize every normal window" rule blows the 240×140 frameless window up to
full screen, and Wayland forbids client-side corner positioning. A Plasma applet is the
KDE-native home for an always-available drop target — the panel is always visible, the icon
itself is the drop zone, and window rules do not apply.

## Goals

- Drop one or more files onto the panel icon → optimize them via `klop optimize` (async).
- Popup shows: running **saved total**, a **recent history list** (name, before→after, %),
  and an **Undo** button on undoable file rows.
- A **Configure** action opens a QML form editing the optimizer settings, persisted to the
  same `~/.config/klop/config.toml` the CLI/daemon already read.
- Two new Qt-free CLI subcommands back the form: `klop config get [--json]` and
  `klop config set key=value …`.
- An installer: `klop install-plasmoid` deploys the package and pins the absolute path to
  `klop` so plasmashell's PATH does not matter.
- Remove the now-redundant floating `DropTargetWindow` from the daemon.

## Non-Goals

- No D-Bus service / live push updates (that is Sub-project B). The popup refreshes on open
  and after each action.
- No tray-daemon removal beyond deleting the floating drop window; the daemon keeps clipboard
  auto-optimize.
- No new runtime Python dependencies. TOML is written with a tiny hand-rolled serializer for
  the flat, known `Config` schema.
- No clipboard-undo from the plasmoid (clipboard rows are view-only, per the history spec).
- No downscale / drag-out / video-PDF UI in this sub-project.

## Architecture

```
Panel applet (QML, org.trungld.klop)
  compact rep  = icon + DropArea   ── drop files ─▶ klop optimize <files>
  full rep     = popup
                   ├─ "Saved X"        ◀── sum(saved_bytes) from history
                   ├─ history list     ◀── klop history --json
                   │    └─ Undo (file) ──▶ klop undo <id>
                   └─ Configure ▶ config page (form)
                        get  ◀── klop config get --json
                        set  ──▶ klop config set key=value …
```

All arrows are process invocations through `Plasma5Support.DataSource` (executable engine).
The plasmoid holds no persistent state of its own; the CLI + `history.jsonl` + `config.toml`
are the single sources of truth.

### Why shell-out (chosen) over D-Bus

The Qt-free CLI already *is* the backend entrypoint (`optimize`, `history`, `undo`). Adding
`config get/set` completes the surface the UI needs. Shell-out keeps the QML declarative and
testable at the CLI layer, needs no daemon, and matches the original design's key property
("M0's CLI entrypoint doubles as the backend"). Process-spawn overhead is irrelevant for
user-driven, human-paced actions. A D-Bus service would give live updates but requires
building and running Sub-project B; deferred.

## Components

### New CLI subcommands (`cli.py`, `config.py`) — Qt-free, TDD

**`config.py` additions**

- `save_config(config: Config, path: Path | None = None) -> None`
  - Serializes the known `Config` fields to TOML and writes atomically (temp file in the same
    dir + `os.replace`). Creates the parent dir on first write.
  - Serializer handles the flat schema only: `bool` → `true/false`, `int` → decimal,
    `tuple[int,int]` (`pngquant_quality`) → `[min, max]`. No comments preserved; the file is
    normalized to the current effective config. Unknown/legacy keys are dropped (they were
    already ignored by `load_config`).

- `apply_overrides(config: Config, overrides: dict[str, str]) -> Config`
  - Validates each key against `Config` field names (unknown key → `ValueError`).
  - Coerces the string value to the field's type:
    - `bool`: `"true"/"false"/"1"/"0"/"yes"/"no"` (case-insensitive) → bool; else `ValueError`.
    - `int`: `int(value)`; non-numeric → `ValueError`.
    - `tuple[int,int]` (`pngquant_quality`): `"65,80"` → `(65, 80)`; malformed → `ValueError`.
  - Returns a new frozen `Config` (via `dataclasses.replace`).

**`cli.py` additions**

- `_cmd_config_get(args)`: `config = load_config()`. If `--json`, print
  `json.dumps(_config_to_dict(config))` where `pngquant_quality` is a 2-element list; else
  print `key = value` lines. Exit 0.
- `_cmd_config_set(args)`: parse `args.assignments` (each `"key=value"`; malformed → error to
  stderr, exit 2). `apply_overrides(load_config(), overrides)` → on `ValueError` print the
  message to stderr, exit 2. `save_config(updated)`. Print the resulting effective config (so
  the plasmoid can update its form from one call). Exit 0.
- Subparsers: `config` with a nested `get`/`set`, or two flat parsers `config-get`/
  `config-set`. **Decision:** a `config` parser with a required `get|set` sub-subparser
  (`klop config get`, `klop config set k=v …`). Keep import of `config`/`json`
  top-level (already Qt-free).

### The plasmoid package (`plasmoid/package/`)

Standard Plasma 6 `Plasma/Applet` package:

- `metadata.json` — `KPlugin.Id = "org.trungld.klop"`, `KPlugin.Name = "Klop"` (the applet's
  visible name; the popup header/tooltip use "Klop" too), icon, category
  "Utilities", `X-Plasma-API-Minimum-Version` for Plasma 6, `KPackageStructure =
  "Plasma/Applet"`.
- `contents/ui/main.qml` — root `PlasmoidItem`:
  - `compactRepresentation`: an icon (`Kirigami.Icon`) wrapped in a `DropArea` that accepts
    `text/uri-list`; on drop, extract local paths and run `optimize`. `preferredRepresentation`
    stays compact so it sits on the panel.
  - `fullRepresentation`: the popup (see below).
  - Owns the shared `Plasma5Support.DataSource` (executable engine) and helper JS functions
    `runOptimize(paths)`, `refreshHistory()`, `runUndo(id)`, `configGet()`, `configSet(map)`.
- `contents/ui/FullRepresentation.qml` — `ColumnLayout`:
  - Header row: "Saved {human total}" + a refresh/optimize busy indicator.
  - `ListView` bound to a `ListModel` filled from `history --json` (newest first). Delegate
    shows name, `before → after (-N%)`, and an Undo `ToolButton` visible only when the row is
    undoable (`backup_id != null && !undone`).
  - Footer: a "Configure" button (opens the config page / triggers the applet config action).
- `contents/ui/ConfigGeneral.qml` — the optimizer settings form (see below), registered via
  `contents/config/config.qml` + `main.xml` **or** opened as an in-popup page.
  **Decision:** use Plasma's standard applet **configuration dialog** with a single
  "General" page whose QML reads current values via `config get --json` on load and writes via
  `config set` on Apply. (We deliberately do *not* use KConfigXT storage — the form's source of
  truth is `config.toml` via the CLI, matching the "one source of truth" goal. The KCM page is
  just a host for our QML form.)
- `contents/code/backend.js` (generated/edited at install) — exports `KLOP_BIN`, the absolute
  path to `klop`. `main.qml` imports it so every invocation uses the absolute binary,
  independent of plasmashell's PATH.

The config **form fields** (v1): `png_lossy` (switch), `pngquant_quality` min/max (two spin
boxes, min ≤ max enforced in UI), `jpeg_max_quality` (spin 1–100), `min_bytes_saved` (spin),
`concurrency` (spin 1–N), `clipboard_watch` (switch). `backup_retention_days` /
`backup_max_bytes` are out of scope for the v1 form (still editable via TOML).

### Installer (`cli.py` `install-plasmoid`)

- Resolve the plasmoid package dir shipped in the repo (`plasmoid/package/`, located relative
  to the installed Python package or repo root — resolve via `importlib`/`__file__` with a
  repo fallback).
- Write `contents/code/backend.js` with `KLOP_BIN = "<abs path from resolve_exec()>"` (reuse
  `servicemenu.resolve_exec()`), then install:
  - Prefer `kpackagetool6 -t Plasma/Applet -i <dir>` (or `-u` if already installed).
  - Fallback: copy the package into `~/.local/share/plasma/plasmoids/org.trungld.klop/`.
- Print next steps: add the widget to a panel (and, if needed, restart plasmashell so the new
  package is discovered).

### Cleanup — remove the floating drop window

- Delete `droptarget.py` and `tests/test_droptarget.py`.
- In `daemon.py`, drop the `DropTargetWindow` construction, its `position_at_corner`/`show`
  wiring, and the `droptarget` field on the `Daemon` NamedTuple. The `queue.submit` path stays
  (used by the plasmoid via the CLI, and by future sources). Update `tests/test_daemon.py`
  (remove `test_build_daemon_shows_drop_target_at_corner` and any `droptarget` references).
- The daemon remains a clipboard-auto-optimize + notifications background process.

## Data flow details

- **Optimize on drop:** `main.qml` gets dropped URLs, keeps only local files, calls
  `runOptimize(paths)` → `DataSource` runs `KLOP_BIN optimize <quoted paths>`. The CLI (non-tty
  under plasmashell) posts the summary desktop notification itself. On `exited`, the plasmoid
  calls `refreshHistory()` and recomputes the saved total.
- **History + saved total:** `refreshHistory()` runs `KLOP_BIN history --json`, parses stdout,
  repopulates the `ListModel`, and sets `savedTotal = Σ max(0, original-new)`. Called on popup
  open and after optimize/undo.
- **Undo:** delegate button runs `KLOP_BIN undo <backup_id>`; on exit, `refreshHistory()`
  (the row now shows `[undone]` / loses its button).
- **Config:** on config-page load, `configGet()` runs `config get --json` and binds the form;
  on Apply, `configSet(map)` runs `config set k=v …` and re-reads to confirm.

## Error handling

- **`config set` bad key/value:** CLI exits 2 with a stderr message; the form surfaces it as an
  inline error and leaves the file unchanged (`apply_overrides` raises before `save_config`).
- **`klop` not found / nonzero exit:** the `DataSource` exit handler checks the exit code;
  on failure the popup shows a small inline error (stderr text) and does not clear state.
- **`history --json` empty / malformed:** empty list → "No optimizations yet"; a parse failure
  leaves the previous list and logs to console (best-effort UI).
- **PATH independence:** `KLOP_BIN` is an absolute path baked at install; if the file no longer
  exists, invocations fail and surface the inline error (user re-runs `install-plasmoid`).
- **Atomic config writes:** `save_config` writes a temp file + `os.replace`, so a crash mid-write
  never truncates `config.toml`.

## Testing strategy

Automated tests cover the Python surface (headless, Qt-free); the QML is kept thin and verified
by manual smoke.

- **`config.py`:**
  - `save_config` + `load_config` round-trip preserves every field, including
    `pngquant_quality` as a tuple.
  - `save_config` writes atomically (result parses; parent dir created).
  - `apply_overrides`: valid bool/int/tuple coercion; `min ≤ max` not enforced here (UI concern);
    unknown key → `ValueError`; non-numeric int → `ValueError`; malformed tuple → `ValueError`.
- **`cli.py`:**
  - `config get --json` emits a JSON object with all fields; `pngquant_quality` is a 2-list.
  - `config set png_lossy=false jpeg_max_quality=70` writes the file so a subsequent
    `load_config()` reflects it; prints the effective config; exit 0.
  - `config set bogus=1` → exit 2, stderr mentions the bad key, file unchanged.
  - Both keep the CLI Qt-free (`assert "PySide6" not in sys.modules`).
  - `install-plasmoid` (with a tmp target + fake `kpackagetool6`/copy) writes `backend.js`
    containing the resolved absolute path and deploys the package. (Shell-out mocked.)
- **`daemon.py`:** after removing the drop window, `build_daemon` still wires clipboard +
  history + router; no `droptarget` attribute; existing clipboard/history tests stay green.
- **Manual smoke (real Plasma 6 session):** `klop install-plasmoid`, add the widget to a
  panel; drag an image onto the icon → it shrinks and a notification appears; open the popup →
  the optimization shows in history with the right savings and an Undo button; Undo restores and
  the row flips to undone; open Configure → change JPEG quality → Apply → `klop config get`
  and the TOML both reflect it.

## Dependencies

- Runtime: KDE Plasma 6 (Qt6/KF6), `kpackagetool6` for install (fallback: plain copy). No new
  Python packages. QML uses `org.kde.plasma.plasmoid`, `org.kde.plasma.components`,
  `org.kde.kirigami`, `org.kde.plasma.plasma5support` (executable `DataSource`).
- The `klop` CLI must be installed (as it already is at `~/.local/bin/klop`).

## Build order (for the implementation plan)

1. **CLI config surface** — `config.py` (`save_config`, `apply_overrides`) + `cli.py`
   (`config get`/`config set`), fully TDD. No UI risk; unblocks the form.
2. **Remove floating drop window** — delete `droptarget.py`/tests, update `daemon.py`/tests.
3. **Plasmoid package** — `metadata.json`, `main.qml` (compact DropArea + optimize),
   `FullRepresentation.qml` (saved total + history + undo), `ConfigGeneral.qml` (form).
4. **Installer** — `install-plasmoid` (backend.js abs-path bake + `kpackagetool6`/copy).
5. **Manual smoke** on the real session; iterate QML.
