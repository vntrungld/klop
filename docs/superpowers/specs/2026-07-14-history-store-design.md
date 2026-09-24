# Klop — Optimization History Store Design Spec

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan
**Sub-project A of the applet direction.** Builds on M0 (engine/backup), M2 (clipboard),
M3 (overlay/router). The foundation the Plasma applet (Sub-project C) will render; the
headless-daemon/bridge refactor (Sub-project B) comes after and does not block this.

## Summary

Record every optimization — **file** and **clipboard** — to a durable, queryable history at
`~/.local/share/klop/history.jsonl`: name, sizes, saved bytes, timestamp, kind, and (for
files) the `backup_id` that makes it undoable. Expose it two ways: a new `klop history
[--json]` command (the plasmoid's data source) and an in-process `HistoryStore` the daemon and
CLI append to. **File** rows are undoable indefinitely (persistent disk backup); **clipboard**
rows are **view-only**. As part of nailing down what is undoable, collapse the clipboard undo to
a **single most-recent slot** (see below).

## Scope decisions (from brainstorming)

- **Clipboard rows are view-only.** They show savings but carry no `backup_id` and no Undo —
  there is no persistent original to restore from.
- **Clipboard undo is single-slot and transient.** Only the *current* (most-recent) clipboard
  optimization is undoable, via its own notification, right after it happens. A new clipboard
  optimization supersedes the previous one. This is *why* clipboard history rows are view-only:
  by the time you scroll history, "the current image" has moved on. `ClipboardWatcher`'s bounded
  16-entry `_undo_store` collapses to one held original.
- **File undo is unchanged.** Every file optimization has a persistent backup (`backup_id`), so
  file history rows keep their Undo indefinitely, backed by `BackupStore`.

## Goals

- A Qt-free `HistoryStore` persisting `HistoryEntry` records as JSON Lines, capped/pruned to the
  most recent ~200 entries.
- Every producer appends: CLI `optimize` (file), daemon `ResultRouter` (file), daemon clipboard
  handler (clipboard, view-only).
- Undo paths mark the corresponding file row undone: CLI `undo`, daemon overlay/notification
  file-undo.
- `klop history [--json]` reads the store — JSON array for the plasmoid, a human table
  otherwise.
- Keep the headless CLI Qt-free (`history.py` imports no Qt).

## Non-Goals

- No plasmoid/UI here (that is Sub-project C). No tray removal (that is Sub-project B).
- No clipboard undo from history, and no multi-image clipboard undo (single-slot, above).
- No new external dependencies. No config keys beyond the data-dir path convention.
- No cross-process locking beyond a best-effort atomic rewrite (single-daemon assumption; see
  Error handling).

## Data model — `HistoryEntry`

A frozen dataclass, JSON-serializable:

| field | type | notes |
|-------|------|-------|
| `id` | `str` | unique per entry; monotonic (`f"{timestamp_ns}-{counter}"` style, generated at record time). Plasmoid row key. |
| `kind` | `str` | `"file"` or `"clipboard"`. |
| `name` | `str` | filename (file) or `"Clipboard image"` (clipboard). |
| `path` | `str | None` | absolute file path (file); `None` for clipboard. |
| `original_size` | `int` | bytes. |
| `new_size` | `int` | bytes. |
| `backup_id` | `str | None` | `BackupStore` id for files (enables Undo); `None` for clipboard. |
| `timestamp` | `float` | unix seconds (`time.time()`), record time. |
| `undone` | `bool` | `False` at record; flipped by `mark_undone`. |

- Property `saved_bytes = max(0, original_size - new_size)` (mirrors `JobResult`/`ClipboardResult`).
- `to_dict()` / `from_dict(d)` for JSONL round-trip; `from_dict` tolerates missing `undone`
  (defaults `False`) and unknown keys (forward-compat).
- **Undoable** is derived, not stored: `entry.backup_id is not None and not entry.undone`.

## Component — `history.py` (`HistoryStore`), Qt-free

- **Location:** `~/.local/share/klop/history.jsonl`. Overridable via
  `KLOP_HISTORY_FILE` (points at the file directly — tests set it to a tmp path).
- Constructor `HistoryStore(path: Path | None = None)`; `None` → default resolved from env/home.
  Ensures the parent dir exists lazily on first write (does not create on read).

- `record(kind, name, path, original_size, new_size, backup_id=None) -> HistoryEntry`
  - builds the entry (generates `id` + `timestamp`), appends it as one JSON line (open in append
    mode, one `write` of `json.dumps(...) + "\n"`),
  - then prunes: if the line count exceeds the cap (`_MAX = 200`), rewrite the file atomically
    with only the last `_MAX` lines (write a temp file in the same dir, `os.replace`).
  - returns the entry (callers may want its `id`).

- `entries() -> list[HistoryEntry]`
  - reads the file, parses each line, returns **newest-first** (reverse file order).
  - missing file → `[]`; a corrupt/half-written trailing line is skipped, not fatal.

- `mark_undone(backup_id: str) -> bool`
  - finds the entry whose `backup_id` matches (there is at most one — backup ids are unique),
    sets `undone=True`, rewrites the file atomically; returns whether a row was updated.
  - a no-op returning `False` if the file is missing or no row matches.

Constants: `_MAX = 200`.

## Producer / consumer wiring

```
CLI  optimize(file) ─ OPTIMIZED ─▶ store.record("file", name, path, orig, new, backup_id)
CLI  undo(backup_id) ─ success ──▶ store.mark_undone(backup_id)

daemon file job     ─ OPTIMIZED ─▶ ResultRouter.on_job_done → store.record("file", …, backup_id)
daemon clipboard    ─ optimized ─▶ handler → store.record("clipboard", "Clipboard image",
                                                           None, orig, new, backup_id=None)
daemon file undo    ─ overlay/notification Undo ─▶ store.mark_undone(backup_id)

klop history [--json] ─▶ store.entries() → print
```

### `cli.py`

- `_cmd_optimize`: on `JobStatus.OPTIMIZED`, after printing, `store.record("file", path.name,
  str(path), result.original_size, result.new_size, result.backup_id)`. One `HistoryStore()`
  built per invocation (cheap; no Qt).
- `_cmd_undo`: on a successful `store.restore(...)`, call `history.mark_undone(args.backup_id)`
  (the backup id *is* the history row's `backup_id`).
- New `_cmd_history(args)`: `entries = HistoryStore().entries()`; if `--json`, print
  `json.dumps([e.to_dict() for e in entries])`; else a human table (name, kind, savings, when,
  and `↩` marker for undoable rows). Register subparser `history` with `--json`.
- Import of `history` is a plain top-level import (Qt-free) — the Qt-free CLI invariant holds.

### `results.py` (`ResultRouter`)

- Constructor gains an optional `history=None`. `on_job_done`, on `OPTIMIZED` (after
  `record_saved`/`show_result`), calls `self._history.record("file", Path(result.path).name,
  str(result.path), result.original_size, result.new_size, result.backup_id)` when `history` is
  set. Stays Qt-free (imports only `history`, `job`, `pathlib`).

### `daemon.py` (wiring)

- Build one `HistoryStore()` in `build_daemon`; pass it into `ResultRouter(tray, overlay,
  notifier, history=store)`.
- Clipboard: in `_on_clipboard_optimized`, after `record_saved`/notify, `store.record(
  "clipboard", "Clipboard image", None, result.original_size, result.new_size)`.
- File undo marks the row undone: wrap the overlay's and notifier's file `undo_fn` so a
  successful `engine.undo(backup_id)` is followed by `store.mark_undone(backup_id)`. Concretely,
  pass `undo_fn=_undo_and_record` where `_undo_and_record(bid)` calls `engine.undo(bid)` then
  `store.mark_undone(bid)`. (Clipboard undo stays `watcher.undo`, untouched — no history row to
  mark.)

### `clipboard.py` (`ClipboardWatcher`) — single-slot undo

- Replace the `_undo_store: OrderedDict[str, bytes]` (+ `_UNDO_MAX`, `_undo_counter`) with a
  single held slot: `self._undo_original: bytes | None` and `self._undo_token: str | None`.
- On a new optimized result: set `_undo_original = original`, bump a monotonic token
  (`_undo_token = str(n)`), emit `ClipboardResult(..., undo_token=_undo_token)`. The previous
  slot is discarded (superseded).
- `undo(token)`: restore only if `token == self._undo_token` and `_undo_original is not None`;
  then clear the slot (a token is single-use). Unknown/stale token → no-op.
- No functional change to `optimized`/`started`/`finished` or the notification flow; only the
  undo store shrinks to one. (This keeps the last-image Undo working while dropping the 16-entry
  history that the new model says is meaningless.)

## Error handling

- **Concurrency / atomicity:** the daemon's file queue runs ≤2 workers and the clipboard pool is
  serial, so `record` can be called concurrently. Append is a single `write` (atomic enough for
  line-oriented JSONL on local fs); prune and `mark_undone` rewrite via temp-file + `os.replace`
  (atomic swap). The CLI and daemon are not expected to write concurrently in practice; if they
  do, a lost prune/mark is tolerable (the store self-heals on the next write). No file locking.
- **Corrupt lines:** `entries()` skips any line that fails to parse (e.g. a torn trailing write),
  so a partial write never breaks reads.
- **Missing file / dir:** reads return `[]`; the first write creates the dir and file.
- **`mark_undone` on an already-undone or missing row:** returns `False`, no error.
- **Unbounded growth:** prevented by the `_MAX = 200` prune on every `record`.

## Testing strategy

Headless, mostly pure Python (no Qt for `history.py`/CLI tests). Point `KLOP_HISTORY_FILE` at
a `tmp_path` file.

- **history.py:**
  - `record` appends a line and returns an entry with a unique `id`, correct `saved_bytes`,
    `undone=False`; `entries()` returns it.
  - N > 200 records → the file holds exactly 200 lines, newest kept, oldest pruned.
  - `entries()` is newest-first; a hand-written corrupt trailing line is skipped, earlier
    entries still parse.
  - `mark_undone(bid)` flips exactly the matching row's `undone` to `True` and returns `True`;
    an unknown id returns `False` and changes nothing; a missing file returns `False`.
  - `to_dict`/`from_dict` round-trip; `from_dict` tolerates a missing `undone` key.
- **cli.py:**
  - `optimize` on a shrinkable fixture writes one `kind="file"` row with the printed `backup_id`.
  - `undo <id>` after that optimize sets the row's `undone=True` (via `entries()`).
  - `history --json` emits a JSON array parseable back to the recorded entries; `history`
    (no flag) prints a table including the name and savings. Both leave the CLI Qt-free
    (`assert "PySide6" not in sys.modules` after import).
- **results.py:** a fake history double records; an OPTIMIZED `on_job_done` calls
  `history.record` with the file fields; ERROR/UNCHANGED/SKIPPED do not record. No history set →
  no crash.
- **clipboard.py:** two successive optimized results — `undo(second_token)` restores; the old
  first token is now a no-op (single-slot supersession). `undo` of the current token twice: the
  second call is a no-op (single-use).
- **daemon.py:** emitting a file OPTIMIZED `job_done` records a `"file"` row; a clipboard
  `optimized` records a `"clipboard"` row (path `None`, no `backup_id`); the wrapped file
  `undo_fn` calls both `engine.undo` and `store.mark_undone` (verified via fakes).
- **Manual smoke (real session):** optimize a file via CLI and copy an image with the daemon
  running; `klop history` shows both, the file row marked undoable; `klop undo <id>`
  then shows it undone; `history --json` parses.

## Dependencies

None new. Standard library only (`json`, `os`, `time`, `tempfile`, `pathlib`, `dataclasses`).
