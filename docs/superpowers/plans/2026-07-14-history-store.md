# Optimization History Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every file and clipboard optimization to a durable, queryable JSONL history, exposed via `klop history [--json]` and consumed in-process by the CLI and daemon.

**Architecture:** A Qt-free `HistoryStore` appends `HistoryEntry` records to `~/.local/share/klop/history.jsonl` (capped at 200, atomic rewrite on prune/mark-undone). Producers (CLI `optimize`, daemon `ResultRouter`, daemon clipboard handler) append; undo paths (CLI `undo`, daemon overlay/notification file-undo) call `mark_undone`. File rows are undoable via `backup_id`; clipboard rows are view-only, and clipboard undo collapses to a single most-recent slot.

**Tech Stack:** Python 3.14, standard library only (`json`, `os`, `time`, `tempfile`, `pathlib`, `dataclasses`). PySide6 only in the already-Qt daemon/clipboard units. pytest.

## Global Constraints

- **Qt-free CLI:** `history.py` and `cli.py` must import no Qt. Guard: after `import klop.cli`, `"PySide6" not in sys.modules`.
- **No new dependencies.** Standard library only.
- **Data location:** `~/.local/share/klop/history.jsonl`; override via env `KLOP_HISTORY_FILE` (points at the file directly).
- **History cap:** `_MAX = 200` entries, pruned oldest-first on every `record`.
- **Commit format** (from CLAUDE.md): first line `{Action}: {desc}` with Action ∈ `Update`/`Fix`/`WIP`/`Hotfix`, imperative, <72 chars; blank line; body; `Co-Authored-By: Claude <noreply@anthropic.com>` trailer. (The example `feat:` messages below are illustrative — translate each to this format, e.g. `Update: add HistoryStore JSONL persistence`.)
- **Clipboard rows are view-only:** `kind="clipboard"` records carry `path=None`, `backup_id=None`; they never get an Undo.
- **Clipboard undo is single-slot:** only the most-recent clipboard optimization is undoable, via its notification.

---

## File Structure

- **Create** `src/klop/history.py` — `HistoryEntry` dataclass + `HistoryStore` (record/entries/mark_undone). Qt-free. (Task 1)
- **Create** `tests/test_history.py` — unit tests for the store. (Task 1)
- **Modify** `tests/conftest.py` — autouse fixture isolating `KLOP_HISTORY_FILE` per test so no test writes the real history file. (Task 1)
- **Modify** `src/klop/cli.py` — `optimize` records, `undo` marks undone, new `history` subcommand. (Task 2)
- **Modify** `tests/test_cli.py` — CLI history tests. (Task 2)
- **Modify** `src/klop/results.py` — `ResultRouter` optional `history`, records file OPTIMIZED. (Task 3)
- **Modify** `tests/test_results.py` — router recording tests. (Task 3)
- **Modify** `src/klop/clipboard.py` — single-slot clipboard undo. (Task 4)
- **Modify** `tests/test_clipboard.py` — replace bounded-store test with supersession test. (Task 4)
- **Modify** `src/klop/daemon.py` — build store, wire router/clipboard/file-undo. (Task 5)
- **Modify** `tests/test_daemon.py` — daemon recording + undo-marks-undone tests. (Task 5)

---

## Task 1: HistoryStore + HistoryEntry (core)

**Files:**
- Create: `src/klop/history.py`
- Test: `tests/test_history.py`
- Modify: `tests/conftest.py` (add autouse isolation fixture)

**Interfaces:**
- Consumes: nothing (leaf module, stdlib only).
- Produces:
  - `HistoryEntry(id: str, kind: str, name: str, path: str | None, original_size: int, new_size: int, backup_id: str | None, timestamp: float, undone: bool = False)`, frozen dataclass. Properties `saved_bytes: int`, `undoable: bool`. Methods `to_dict() -> dict`, classmethod `from_dict(d: dict) -> HistoryEntry`.
  - `HistoryStore(path: Path | None = None)` with `record(kind, name, path, original_size, new_size, backup_id=None) -> HistoryEntry`, `entries() -> list[HistoryEntry]` (newest-first), `mark_undone(backup_id: str) -> bool`.
  - Module constant `_MAX = 200`.

- [ ] **Step 1: Add the autouse history-isolation fixture to conftest**

Add to `tests/conftest.py` (so no test ever writes the real `~/.local/share/klop/history.jsonl`):

```python
@pytest.fixture(autouse=True)
def _isolate_history(tmp_path, monkeypatch):
    # Point every test's history at its own tmp file; tests that need a
    # specific path override this with their own monkeypatch.setenv.
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(tmp_path / "history.jsonl"))
```

- [ ] **Step 2: Write the failing test for record + entries**

Create `tests/test_history.py`:

```python
import json

from klop.history import HistoryEntry, HistoryStore


def test_record_appends_and_entries_reads_back(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    e = store.record("file", "a.png", "/tmp/a.png", 1000, 400, backup_id="b1")
    assert e.saved_bytes == 600
    assert e.undone is False
    assert e.undoable is True
    got = store.entries()
    assert len(got) == 1
    assert got[0].name == "a.png"
    assert got[0].backup_id == "b1"


def test_clipboard_entry_is_view_only(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    e = store.record("clipboard", "Clipboard image", None, 500, 200)
    assert e.path is None
    assert e.backup_id is None
    assert e.undoable is False


def test_entries_newest_first(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    store.record("file", "first.png", "/tmp/first.png", 10, 5, backup_id="b1")
    store.record("file", "second.png", "/tmp/second.png", 10, 5, backup_id="b2")
    names = [e.name for e in store.entries()]
    assert names == ["second.png", "first.png"]


def test_ids_are_unique(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    ids = {store.record("file", f"f{i}.png", f"/tmp/f{i}.png", 10, 5, backup_id=f"b{i}").id for i in range(5)}
    assert len(ids) == 5
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_history.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'klop.history'`.

- [ ] **Step 4: Implement history.py**

Create `src/klop/history.py`:

```python
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path

_MAX = 200


def _default_history_file() -> Path:
    override = os.environ.get("KLOP_HISTORY_FILE")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "klop" / "history.jsonl"


@dataclass(frozen=True)
class HistoryEntry:
    id: str
    kind: str  # "file" | "clipboard"
    name: str
    path: str | None
    original_size: int
    new_size: int
    backup_id: str | None
    timestamp: float
    undone: bool = False

    @property
    def saved_bytes(self) -> int:
        return max(0, self.original_size - self.new_size)

    @property
    def undoable(self) -> bool:
        return self.backup_id is not None and not self.undone

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "original_size": self.original_size,
            "new_size": self.new_size,
            "backup_id": self.backup_id,
            "timestamp": self.timestamp,
            "undone": self.undone,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HistoryEntry":
        return cls(
            id=d["id"],
            kind=d["kind"],
            name=d["name"],
            path=d.get("path"),
            original_size=d["original_size"],
            new_size=d["new_size"],
            backup_id=d.get("backup_id"),
            timestamp=d["timestamp"],
            undone=d.get("undone", False),
        )


class HistoryStore:
    """Append-only JSONL history of optimizations, capped at _MAX entries.
    Qt-free so the CLI can use it. Reads tolerate a torn trailing line."""

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path is not None else _default_history_file()
        self._counter = 0

    def record(
        self, kind, name, path, original_size, new_size, backup_id=None
    ) -> HistoryEntry:
        ts = time.time()
        self._counter += 1
        entry = HistoryEntry(
            id=f"{int(ts * 1e9)}-{self._counter}",
            kind=kind,
            name=name,
            path=path,
            original_size=original_size,
            new_size=new_size,
            backup_id=backup_id,
            timestamp=ts,
            undone=False,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict()) + "\n")
        self._prune()
        return entry

    def entries(self) -> list[HistoryEntry]:
        return list(reversed(self._read_all()))

    def mark_undone(self, backup_id: str) -> bool:
        if not self._path.exists():
            return False
        rows = self._read_all()
        changed = False
        for i, e in enumerate(rows):
            if e.backup_id == backup_id and not e.undone:
                rows[i] = replace(e, undone=True)
                changed = True
        if changed:
            self._rewrite(rows)
        return changed

    def _read_all(self) -> list[HistoryEntry]:
        if not self._path.exists():
            return []
        out: list[HistoryEntry] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(HistoryEntry.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError):
                    continue  # skip a torn/corrupt line, don't fail the read
        return out

    def _prune(self) -> None:
        rows = self._read_all()
        if len(rows) > _MAX:
            self._rewrite(rows[-_MAX:])

    def _rewrite(self, rows: list[HistoryEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for e in rows:
                fh.write(json.dumps(e.to_dict()) + "\n")
        os.replace(tmp, self._path)  # atomic swap
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_history.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Write the failing tests for prune, mark_undone, corrupt line, round-trip**

Append to `tests/test_history.py`:

```python
def test_prune_caps_at_max(tmp_path):
    from klop.history import _MAX

    store = HistoryStore(tmp_path / "h.jsonl")
    for i in range(_MAX + 5):
        store.record("file", f"f{i}.png", f"/tmp/f{i}.png", 10, 5, backup_id=f"b{i}")
    rows = store.entries()
    assert len(rows) == _MAX
    # newest kept, oldest pruned
    assert rows[0].name == f"f{_MAX + 4}.png"
    assert all(e.name != "f0.png" for e in rows)


def test_mark_undone_flips_matching_row(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    store.record("file", "a.png", "/tmp/a.png", 10, 5, backup_id="b1")
    store.record("file", "c.png", "/tmp/c.png", 10, 5, backup_id="b2")
    assert store.mark_undone("b1") is True
    by_id = {e.backup_id: e for e in store.entries()}
    assert by_id["b1"].undone is True
    assert by_id["b1"].undoable is False
    assert by_id["b2"].undone is False


def test_mark_undone_unknown_is_false(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    store.record("file", "a.png", "/tmp/a.png", 10, 5, backup_id="b1")
    assert store.mark_undone("nope") is False


def test_mark_undone_missing_file_is_false(tmp_path):
    store = HistoryStore(tmp_path / "missing.jsonl")
    assert store.mark_undone("b1") is False


def test_entries_skips_corrupt_trailing_line(tmp_path):
    p = tmp_path / "h.jsonl"
    store = HistoryStore(p)
    store.record("file", "a.png", "/tmp/a.png", 10, 5, backup_id="b1")
    with p.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")  # torn write
    rows = store.entries()
    assert len(rows) == 1
    assert rows[0].name == "a.png"


def test_to_dict_from_dict_roundtrip_and_missing_undone(tmp_path):
    e = HistoryEntry("id1", "file", "a.png", "/tmp/a.png", 10, 5, "b1", 123.0, undone=True)
    assert HistoryEntry.from_dict(e.to_dict()) == e
    d = e.to_dict()
    del d["undone"]
    assert HistoryEntry.from_dict(d).undone is False


def test_missing_file_reads_empty(tmp_path):
    assert HistoryStore(tmp_path / "nope.jsonl").entries() == []
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_history.py -v`
Expected: PASS (11 tests). If prune fails, the implementation from Step 4 already handles it — investigate before editing.

- [ ] **Step 8: Verify the store stays Qt-free**

Run: `python -c "import sys, klop.history; assert 'PySide6' not in sys.modules; print('qt-free ok')"`
Expected: prints `qt-free ok`.

- [ ] **Step 9: Commit**

```bash
git add src/klop/history.py tests/test_history.py tests/conftest.py
git commit -m "Update: add HistoryStore JSONL persistence

Add a Qt-free HistoryStore/HistoryEntry recording each optimization
to ~/.local/share/klop/history.jsonl, capped at 200 entries with
atomic prune and mark_undone. File rows are undoable via backup_id;
clipboard rows are view-only. Reads tolerate a torn trailing line.
Add an autouse conftest fixture isolating the history file per test.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: CLI wiring (optimize records, undo marks undone, history command)

**Files:**
- Modify: `src/klop/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `HistoryStore` (Task 1) — `record(...)`, `entries()`, `mark_undone(backup_id)`; `HistoryEntry.to_dict()`, `.saved_bytes`, `.undoable`, `.undone`.
- Produces: `klop history [--json]` command; side-effect that `optimize` records file rows and `undo` marks them undone.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
import json as _json

from klop.history import HistoryStore


def test_optimize_records_file_history(tmp_path, monkeypatch):
    import shutil as _shutil

    from klop.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(hist))
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
    # Force an OPTIMIZED result without invoking real tools.
    from klop import cli as cli_mod
    from klop.job import JobResult, JobStatus

    f = tmp_path / "a.png"
    f.write_bytes(b"x" * 100)

    class _Eng:
        def optimize(self, job):
            return JobResult(JobStatus.OPTIMIZED, job.source_path, 100, 40, backup_id="bid1")

    monkeypatch.setattr(cli_mod, "_build_engine", lambda: _Eng())
    rc = main(["optimize", str(f)])
    assert rc == 0
    rows = HistoryStore(hist).entries()
    assert len(rows) == 1
    assert rows[0].kind == "file"
    assert rows[0].name == "a.png"
    assert rows[0].backup_id == "bid1"


def test_undo_marks_history_undone(tmp_path, monkeypatch):
    from klop.backup import BackupStore
    from klop.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(hist))
    monkeypatch.setenv("KLOP_BACKUP_DIR", str(tmp_path / "backups"))
    # Seed a history row and a matching backup.
    store = HistoryStore(hist)
    f = tmp_path / "a.png"
    f.write_bytes(b"ORIGINAL")
    bstore = BackupStore(tmp_path / "backups")
    bid = bstore.backup(f)
    store.record("file", "a.png", str(f), 100, 40, backup_id=bid)
    f.write_bytes(b"CHANGED")

    rc = main(["undo", bid])
    assert rc == 0
    assert HistoryStore(hist).entries()[0].undone is True


def test_history_json_outputs_entries(tmp_path, monkeypatch, capsys):
    from klop.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(hist))
    HistoryStore(hist).record("file", "a.png", "/tmp/a.png", 100, 40, backup_id="b1")
    rc = main(["history", "--json"])
    assert rc == 0
    data = _json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["name"] == "a.png"
    assert data[0]["backup_id"] == "b1"


def test_history_table_lists_names(tmp_path, monkeypatch, capsys):
    from klop.cli import main

    hist = tmp_path / "history.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(hist))
    HistoryStore(hist).record("clipboard", "Clipboard image", None, 500, 200)
    rc = main(["history"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Clipboard image" in out
    assert "clipboard" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -k "history or records or marks" -v`
Expected: FAIL — `history` is not a valid subcommand / `optimize` writes no history.

- [ ] **Step 3: Implement the CLI changes**

In `src/klop/cli.py`, add imports near the top (after existing imports):

```python
import json

from .history import HistoryStore
```

Replace `_cmd_optimize` so an OPTIMIZED result records a file row:

```python
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
```

Replace `_cmd_undo` so a successful restore marks the history row undone:

```python
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
```

Add the new `_cmd_history` (place it after `_cmd_undo`):

```python
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
```

Register the subparser in `main` (after the `undo` parser block):

```python
    p_hist = sub.add_parser("history", help="show optimization history")
    p_hist.add_argument("--json", action="store_true", help="output as JSON")
    p_hist.set_defaults(func=_cmd_history)
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `pytest tests/test_cli.py -k "history or records or marks" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full CLI suite + Qt-free guard**

Run: `pytest tests/test_cli.py -v && python -c "import sys, klop.cli; assert 'PySide6' not in sys.modules; print('qt-free ok')"`
Expected: all CLI tests PASS and `qt-free ok` prints.

- [ ] **Step 6: Commit**

```bash
git add src/klop/cli.py tests/test_cli.py
git commit -m "Update: record and query optimization history in CLI

optimize now records each OPTIMIZED file to the history store; undo
marks the matching row undone; and a new 'klop history [--json]'
command reads the store (JSON array for the plasmoid, a table with an
undoable marker otherwise). CLI stays Qt-free.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: ResultRouter records file results

**Files:**
- Modify: `src/klop/results.py`
- Test: `tests/test_results.py`

**Interfaces:**
- Consumes: `HistoryStore.record(kind, name, path, original_size, new_size, backup_id)` (Task 1).
- Produces: `ResultRouter(tray, overlay, notifier, history=None)` — records a `"file"` row on OPTIMIZED when `history` is provided; unchanged routing otherwise.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_results.py`:

```python
class FakeHistory:
    def __init__(self):
        self.records = []

    def record(self, kind, name, path, original_size, new_size, backup_id=None):
        self.records.append((kind, name, path, original_size, new_size, backup_id))


def test_optimized_records_file_history():
    tray, overlay, notifier, history = FakeTray(), FakeOverlay(), FakeNotifier(), FakeHistory()
    ResultRouter(tray, overlay, notifier, history=history).on_job_done(_optimized())
    assert history.records == [("file", "a.png", "/tmp/a.png", 1000, 400, "b1")]


def test_non_optimized_does_not_record():
    tray, overlay, notifier, history = FakeTray(), FakeOverlay(), FakeNotifier(), FakeHistory()
    router = ResultRouter(tray, overlay, notifier, history=history)
    router.on_job_done(JobResult(JobStatus.ERROR, Path("/tmp/a.png"), 0, 0, message="x"))
    router.on_job_done(JobResult(JobStatus.SKIPPED, Path("/tmp/a.png"), 10, 10))
    assert history.records == []


def test_optimized_without_history_does_not_crash():
    tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
    ResultRouter(tray, overlay, notifier).on_job_done(_optimized())  # history=None
    assert len(overlay.shown) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_results.py -k "history or record" -v`
Expected: FAIL — `ResultRouter.__init__` takes no `history` argument.

- [ ] **Step 3: Implement the router change**

In `src/klop/results.py`, update `__init__` and `on_job_done`:

```python
    def __init__(self, tray, overlay, notifier, history=None):
        self._tray = tray
        self._overlay = overlay
        self._notifier = notifier
        self._history = history

    def on_job_done(self, result: JobResult) -> None:
        if result.status == JobStatus.OPTIMIZED:
            self._tray.record_saved(result.saved_bytes)
            self._overlay.show_result(result)  # replaces the pending card
            if self._history is not None:
                p = Path(result.path)
                self._history.record(
                    "file",
                    p.name,
                    str(p),
                    result.original_size,
                    result.new_size,
                    result.backup_id,
                )
        elif result.status == JobStatus.ERROR:
            self._notifier.notify_result(result)
            self._overlay.dismiss()
        else:  # UNCHANGED / SKIPPED
            self._overlay.dismiss()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_results.py -v`
Expected: PASS (all existing + 3 new).

- [ ] **Step 5: Verify results.py stays Qt-free**

Run: `python -c "import sys, klop.results; assert 'PySide6' not in sys.modules; print('qt-free ok')"`
Expected: prints `qt-free ok`.

- [ ] **Step 6: Commit**

```bash
git add src/klop/results.py tests/test_results.py
git commit -m "Update: record file optimizations from ResultRouter

ResultRouter gains an optional history store and records a 'file'
history row on each OPTIMIZED result, mirroring the CLI. Non-optimized
outcomes and a None history are no-ops. Stays Qt-free.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Single-slot clipboard undo

**Files:**
- Modify: `src/klop/clipboard.py`
- Test: `tests/test_clipboard.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ClipboardWatcher.undo(token)` restores only when `token` equals the current (most-recent) token; a superseded/used token is a no-op. The `optimized`/`started`/`finished` signals and `ClipboardResult` are unchanged.

- [ ] **Step 1: Update the existing bounded-store test to the new supersession behavior**

In `tests/test_clipboard.py`, replace `test_watcher_undo_store_is_bounded` (around line 184) with:

```python
def test_watcher_undo_is_single_slot(qapp):
    # Only the most-recent clipboard optimization is undoable; a new
    # optimization supersedes the previous token.
    from klop.clipboard import ClipboardWatcher

    results = []
    calls = {"n": 0}

    def optimize(png):
        calls["n"] += 1
        return png + b"opt" + bytes([calls["n"]])  # always "smaller-ish" distinct output

    clip = qapp.clipboard()
    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=optimize)
    watcher.optimized.connect(results.append)

    def push(data):
        from PySide6.QtCore import QByteArray, QMimeData

        md = QMimeData()
        md.setData("image/png", QByteArray(data))
        clip.setMimeData(md)
        watcher._on_changed()
        watcher.wait_for_done(2000)
        qapp.processEvents()

    push(b"\x89PNG-one")
    push(b"\x89PNG-two")
    assert len(results) >= 2
    first_token, second_token = results[0].undo_token, results[-1].undo_token
    assert first_token != second_token

    # The old (superseded) token no longer restores anything.
    watcher.undo(first_token)  # no-op, must not raise
    # The current token restores; using it twice is a no-op the second time.
    watcher.undo(second_token)
    watcher.undo(second_token)
```

> Note: this test drives `_on_changed` directly (the offscreen clipboard's `dataChanged` may not fire in headless CI) — matching the existing clipboard tests' style. If the existing `test_watcher_undo_restores_original` uses a different driving helper, reuse that helper instead of redefining `push`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_clipboard.py -k single_slot -v`
Expected: FAIL — the test references the new single-slot semantics not yet implemented (old code still uses `_undo_store`).

- [ ] **Step 3: Implement the single-slot undo in clipboard.py**

In `src/klop/clipboard.py`:

Remove the `_UNDO_MAX = 16` constant (keep `_SEEN_MAX = 32`):

```python
_SEEN_MAX = 32
```

In `ClipboardWatcher.__init__`, replace the `_undo_store`/`_undo_counter` lines:

```python
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._undo_original: bytes | None = None  # single most-recent original
        self._undo_token: str | None = None
        self._undo_counter = 0
```

Replace `undo`:

```python
    def undo(self, token: str) -> None:
        if token != self._undo_token or self._undo_original is None:
            return  # superseded, already-used, or unknown token
        original = self._undo_original
        self._undo_original = None
        self._undo_token = None
        self._remember(content_hash(original))  # restoring must not re-trigger optimize
        self._set_clipboard_png(original)
```

Replace the undo-store block inside `_on_result_ready`:

```python
    def _on_result_ready(self, original: bytes, digest: str, optimized) -> None:
        self._remember(digest)  # don't reprocess this exact input
        if optimized is not None:
            self._remember(content_hash(optimized))
            self._undo_counter += 1
            token = str(self._undo_counter)
            self._undo_original = original  # supersede any previous slot
            self._undo_token = token
            self._set_clipboard_png(optimized)
            self.optimized.emit(ClipboardResult(len(original), len(optimized), token))
        self.finished.emit()
```

- [ ] **Step 4: Run the clipboard suite to verify it passes**

Run: `pytest tests/test_clipboard.py -v`
Expected: PASS — the new single-slot test passes and `test_watcher_undo_restores_original` still passes (the current token restores). (An offscreen QClipboard teardown segfault, exit 139, is a known-benign artifact; a non-zero exit *only* at process teardown with all tests reported PASS is acceptable — real Wayland exits 0.)

- [ ] **Step 5: Commit**

```bash
git add src/klop/clipboard.py tests/test_clipboard.py
git commit -m "Update: collapse clipboard undo to a single slot

Only the most-recent clipboard optimization is undoable now; a new
optimization supersedes the previous token, and a used token is a
no-op. Replaces the bounded 16-entry undo store, matching the decision
that clipboard history rows are view-only.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Daemon wiring (store, router, clipboard record, file-undo marks undone)

**Files:**
- Modify: `src/klop/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `HistoryStore` (Task 1), `ResultRouter(..., history=...)` (Task 3).
- Produces: `build_daemon(app, *, engine=None, backend=None, clipboard=None, overlay=None, droptarget=None, history=None)` — records file results (via router) and clipboard results, and a file-undo through the overlay/notification also calls `history.mark_undone`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_daemon.py`:

```python
class FakeHistory:
    def __init__(self):
        self.records = []
        self.undone = []

    def record(self, kind, name, path, original_size, new_size, backup_id=None):
        self.records.append((kind, name, path, original_size, new_size, backup_id))

    def mark_undone(self, backup_id):
        self.undone.append(backup_id)


def test_build_daemon_records_file_result(qapp, tmp_path):
    engine = FakeEngine()
    history = FakeHistory()
    d = build_daemon(qapp, engine=engine, backend=FakeBackend(), history=history)

    d.queue.submit([tmp_path / "z.png"])
    d.queue.wait_for_done(5000)
    qapp.processEvents()

    assert len(history.records) == 1
    kind, name, _path, orig, new, bid = history.records[0]
    assert (kind, name, orig, new, bid) == ("file", "z.png", 1000, 200, "b1")


def test_build_daemon_file_undo_marks_history_undone(qapp, tmp_path):
    engine = FakeEngine()
    history = FakeHistory()
    d = build_daemon(qapp, engine=engine, backend=FakeBackend(), history=history)

    d.queue.submit([tmp_path / "z.png"])
    d.queue.wait_for_done(5000)
    qapp.processEvents()

    d.overlay.undo_button.click()
    assert engine.undone == ["b1"]
    assert history.undone == ["b1"]
```

> The existing `test_build_daemon_file_undo_via_overlay` still passes (it asserts only `engine.undone == ["b1"]`, which the wrapped undo preserves).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_daemon.py -k "records_file or marks_history" -v`
Expected: FAIL — `build_daemon` has no `history` keyword / no records.

- [ ] **Step 3: Implement the daemon wiring**

In `src/klop/daemon.py`:

Add the import (with the other `.` imports):

```python
from .history import HistoryStore
```

Update `build_daemon`'s signature and body. Change the signature line:

```python
def build_daemon(app, *, engine=None, backend=None, clipboard=None, overlay=None, droptarget=None, history=None):
```

Just after `engine = engine or _build_engine()` and `config = load_config()`, build the store and the undo wrapper, and use them for the notifier/overlay/router:

```python
    engine = engine or _build_engine()
    config = load_config()
    history = history or HistoryStore()

    def _undo_file(backup_id):
        engine.undo(backup_id)
        history.mark_undone(backup_id)

    queue = OptimizationQueue(optimize_fn=engine.optimize, concurrency=config.concurrency)
    app.aboutToQuit.connect(lambda: queue.wait_for_done(3000))
    backend = backend or DBusNotificationBackend()
    notifier = Notifier(backend=backend, undo_fn=_undo_file)
    overlay = overlay or ResultOverlay(undo_fn=_undo_file)
    droptarget = droptarget or DropTargetWindow(submit_fn=queue.submit)
    tray = TrayApp(queue=queue, icon=load_tray_icon(), drop_toggle_fn=droptarget.toggle)

    router = ResultRouter(tray, overlay, notifier, history=history)
    queue.job_done.connect(router.on_job_done)
    queue.job_started.connect(router.on_job_started)
```

In `_on_clipboard_optimized`, record the clipboard row (after `tray.record_saved`, before/after the notify — order doesn't matter):

```python
        def _on_clipboard_optimized(result):
            tray.record_saved(result.saved_bytes)
            history.record(
                "clipboard",
                "Clipboard image",
                None,
                result.original_size,
                result.new_size,
            )
            body = (
                f"{human_size(result.original_size)} → "
                f"{human_size(result.new_size)} "
                f"(-{percent_saved(result.original_size, result.new_size)}%)"
            )
            token = result.undo_token
            notifier.notify(
                "Clipboard image",
                body,
                undo=lambda: watcher.undo(token),
                undo_confirm="Restored image to clipboard",
            )
```

Add `history` to the returned `Daemon(...)`? Not required by the tests, but if you extend the `Daemon` NamedTuple, add the field in both the class and the constructor call. **Do not** change the NamedTuple for this task (YAGNI — Sub-project B's bridge can add it). Leave the `Daemon(...)` return as-is.

- [ ] **Step 4: Run the daemon suite to verify it passes**

Run: `pytest tests/test_daemon.py -v`
Expected: PASS — new recording/undo tests pass and all existing daemon tests (including `test_build_daemon_file_undo_via_overlay`) still pass.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests PASS (prior 114 + the new history/CLI/results/clipboard/daemon tests). A benign offscreen-teardown exit 139 with all tests reported PASS is acceptable (see Task 4 Step 4).

- [ ] **Step 6: Verify the Qt-free CLI invariant once more end-to-end**

Run: `python -c "import sys, klop.cli; assert 'PySide6' not in sys.modules; print('qt-free ok')"`
Expected: prints `qt-free ok` (daemon/clipboard Qt imports are lazy inside `_cmd_daemon`).

- [ ] **Step 7: Commit**

```bash
git add src/klop/daemon.py tests/test_daemon.py
git commit -m "Update: wire history recording into the daemon

build_daemon now builds a HistoryStore (injectable), passes it to the
ResultRouter for file results, records clipboard results as view-only
rows, and wraps the file undo_fn so an overlay/notification undo also
marks the history row undone.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- `HistoryStore`/`HistoryEntry` model (record/entries/mark_undone, JSONL, cap 200, atomic rewrite, corrupt-line tolerance) → Task 1. ✓
- Env override `KLOP_HISTORY_FILE` → Task 1 (`_default_history_file`). ✓
- CLI `optimize` records, `undo` marks undone, `history [--json]` → Task 2. ✓
- Router records file OPTIMIZED → Task 3. ✓
- Clipboard single-slot undo → Task 4. ✓
- Daemon wiring: store, router history, clipboard record, file-undo mark_undone → Task 5. ✓
- Qt-free invariant guarded → Tasks 1, 2, 3, 5. ✓
- Derived `undoable` (backup_id and not undone) → Task 1. ✓
- Test-isolation so no real history is written → Task 1 conftest fixture. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to Task N"; every code step shows full code. ✓

**3. Type consistency:** `record(kind, name, path, original_size, new_size, backup_id=None)` signature identical across history.py, cli.py, results.py, daemon.py, and all fakes. `mark_undone(backup_id) -> bool` consistent. `HistoryEntry` field names match `to_dict`/`from_dict` and the JSON keys asserted in CLI tests (`name`, `backup_id`). `undoable`/`undone` used consistently. ✓

**Open note for the executor:** the clipboard test in Task 4 Step 1 assumes the existing `test_watcher_undo_restores_original` drives the watcher a particular way; before writing the new test, read that existing test and reuse its clipboard-driving helper rather than the illustrative `push` here, to stay consistent with the file.
