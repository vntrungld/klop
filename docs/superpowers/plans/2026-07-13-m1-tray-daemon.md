# Klop M1 — Tray Daemon + Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the headless M0 engine in a PySide6 system-tray daemon that optimizes files picked from a tray menu, runs jobs off the GUI thread, and shows desktop notifications with an Undo action.

**Architecture:** A new `klop daemon` subcommand starts a `QApplication` with a `QSystemTrayIcon`. A tray "Optimize files…" action feeds an `OptimizationQueue` (a `QThreadPool` wrapping M0's `Engine`), which emits `job_done` on the GUI thread. A `Notifier` shows a desktop notification per result via a D-Bus backend and restores originals when the Undo action fires. The M0 engine, config, and CLI are reused unchanged; the headless CLI never imports Qt.

**Tech Stack:** Python 3.11+, PySide6 (Qt6) — `QtCore`, `QtWidgets`, `QtGui`, `QtDBus`; pytest with `QT_QPA_PLATFORM=offscreen` for headless GUI tests. Reuses M0's `Engine`/`BackupStore`/optimizer registry.

## Global Constraints

- **Python 3.11+**; PySide6 installs via its `cp310-abi3` stable-ABI wheel (works on 3.14).
- **The headless CLI must not import Qt.** `optimize`/`undo`/`caps` stay pure-Python; only the `daemon` code path imports PySide6, via lazy imports.
- **Reuse M0 unchanged:** do not modify `engine.py`, `backup.py`, `optimizers.py`, `media.py`, `job.py`, or `config.py` (except imports). M1 is orchestration + UI.
- **Notifications go through an injectable backend** so the Undo logic is unit-tested with a fake; only the thin real backend touches QtDBus.
- **Session-only "Saved" total** (no persistence across restarts in M1).
- **Enabled toggle** gates whether new jobs are accepted (disables the picker when off).
- **Notification policy:** notify on `OPTIMIZED` (with Undo) and `ERROR` (warning, no action); `UNCHANGED`/`SKIPPED` are silent.
- **Commit message format:** first line `{Action}: {desc}` where Action ∈ {Update, Fix, WIP, Hotfix}, imperative, <72 chars; blank line; body; `Co-Authored-By: Claude <noreply@anthropic.com>` trailer. Commit with `git -c user.name='Klop' -c user.email='vn.trungld@gmail.com' commit`.
- **Dev commands:** use `.venv/bin/pytest` and `.venv/bin/pip`. The `klop` console script is `.venv/bin/klop`.

## File Structure

```
src/klop/
├── format.py        # NEW: human_size(), percent_saved() — shared byte/percent formatting
├── queue.py         # NEW: OptimizationQueue (QThreadPool wrapping the engine)
├── notifier.py      # NEW: Notifier + NotificationBackend protocol + DBusNotificationBackend
├── app.py           # NEW: TrayApp (QSystemTrayIcon + menu) + load_tray_icon()
├── daemon.py        # NEW: build_daemon() + run_daemon() wiring
├── assets/tray.svg  # NEW: bundled tray icon
└── cli.py           # MODIFY: import human_size from format; add `daemon` subcommand
tests/
├── conftest.py      # MODIFY: add session-scoped qapp fixture (offscreen QApplication)
├── test_format.py   # NEW: moved _human tests + percent_saved
├── test_queue.py    # NEW
├── test_notifier.py # NEW
├── test_app.py      # NEW
├── test_daemon.py   # NEW
└── test_cli.py      # MODIFY: drop the _human unit tests + _human import (moved to test_format)
```

---

## Task 1: Extract shared formatting (`format.py`)

**Files:**
- Create: `src/klop/format.py`
- Create: `tests/test_format.py`
- Modify: `src/klop/cli.py` (remove `_human`; import `human_size`)
- Modify: `tests/test_cli.py` (remove the 5 `_human` tests + the `_human` import)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `klop.format.human_size(n: float) -> str` — the exact byte formatter moved from `cli._human` (e.g. `500`→`"500B"`, `2048`→`"2.0KB"`, `1048576`→`"1.0MB"`, `3*1024**3`→`"3.0GB"`).
  - `klop.format.percent_saved(original: int, new: int) -> int` — integer percent reduction; `0` when `original <= 0`.

- [ ] **Step 1: Write the failing test `tests/test_format.py`**

```python
from klop.format import human_size, percent_saved


def test_human_bytes():
    assert human_size(500) == "500B"


def test_human_kilobytes():
    assert human_size(2048) == "2.0KB"


def test_human_kilobytes_fractional():
    assert human_size(1536) == "1.5KB"


def test_human_megabytes():
    assert human_size(1048576) == "1.0MB"


def test_human_gigabytes():
    assert human_size(3 * 1024**3) == "3.0GB"


def test_percent_saved_typical():
    assert percent_saved(8579, 3431) == 60


def test_percent_saved_zero_original():
    assert percent_saved(0, 0) == 0


def test_percent_saved_no_reduction():
    assert percent_saved(1000, 1000) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_format.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.format'`.

- [ ] **Step 3: Create `src/klop/format.py`**

```python
from __future__ import annotations


def human_size(n: float) -> str:
    """Format a byte count as a short human-readable string (e.g. '2.0KB')."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.0f}B"


def percent_saved(original: int, new: int) -> int:
    """Integer percentage reduction from original to new size (0 if original <= 0)."""
    if original <= 0:
        return 0
    return round((original - new) / original * 100)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_format.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Update `src/klop/cli.py` to use the shared formatter**

Delete the `_human` function (lines 22-27) and its blank lines. Add `from .format import human_size` to the imports (after the other `from .` imports). Replace the three `_human(` calls in `_cmd_optimize` with `human_size(`. The `_cmd_optimize` optimized branch becomes:

```python
        if result.status == JobStatus.OPTIMIZED:
            print(
                f"optimized {path.name}: "
                f"{human_size(result.original_size)} -> {human_size(result.new_size)} "
                f"(saved {human_size(result.saved_bytes)}, undo id {result.backup_id})"
            )
```

The import block at the top of `cli.py` should now include:

```python
from .backup import BackupStore
from .capabilities import KNOWN_TOOLS, detect_capabilities
from .config import load_config
from .engine import Engine
from .format import human_size
from .job import JobStatus, OptimizationJob
```

- [ ] **Step 6: Update `tests/test_cli.py` — remove the moved `_human` tests**

Change the import line 7 from `from klop.cli import _human, main` to:

```python
from klop.cli import main
```

Delete the five test functions `test_human_bytes`, `test_human_kilobytes`, `test_human_kilobytes_fractional`, `test_human_megabytes`, `test_human_gigabytes` (lines 12-29). Leave every other test in the file unchanged.

- [ ] **Step 7: Run the full suite to verify no regressions**

Run: `.venv/bin/pytest -q`
Expected: PASS. Count is unchanged overall (5 `_human` tests moved from test_cli to test_format; 3 new `percent_saved` tests added), so total is 45 (was 42, +3 percent_saved).

- [ ] **Step 8: Commit**

```bash
git add src/klop/format.py tests/test_format.py src/klop/cli.py tests/test_cli.py
git commit -m "Update: extract byte formatting into shared format module

Move the _human byte formatter out of cli.py into format.py as
human_size() and add percent_saved(), so the upcoming notifier and the
CLI share one implementation. Relocate the formatter unit tests to
test_format.py and add percent_saved coverage.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: OptimizationQueue + PySide6 dependency (`queue.py`)

**Files:**
- Modify: `pyproject.toml` (add PySide6 runtime dependency)
- Create: `src/klop/queue.py`
- Modify: `tests/conftest.py` (add the `qapp` fixture)
- Test: `tests/test_queue.py`

**Interfaces:**
- Consumes: `klop.job.OptimizationJob`, `JobResult`, `JobStatus`.
- Produces:
  - `klop.queue.OptimizationQueue(optimize_fn, concurrency=2, parent=None)` — a `QObject` with a `job_done = Signal(object)` that carries a `JobResult`.
  - `.submit(paths: list[Path]) -> None` — enqueues one job per path; each runs `optimize_fn(OptimizationJob(source_path=path))` on a `QThreadPool` worker and emits `job_done` with the result (or a synthesized `JobResult(status=ERROR, ...)` if `optimize_fn` raises).
  - `.wait_for_done(msec: int = -1) -> bool` — blocks until all queued jobs finish (used by tests and by graceful shutdown).
  - Shared test fixture `qapp` (in conftest) — a session-scoped offscreen `QApplication`.

- [ ] **Step 1: Add PySide6 to `pyproject.toml`**

Change the `dependencies` line from `dependencies = []` to:

```toml
dependencies = ["PySide6>=6.6"]
```

- [ ] **Step 2: Install the updated dependencies into the venv**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: installs PySide6 (6.11.x, `cp310-abi3` wheel) and its `shiboken6` companion with no errors. Verify: `.venv/bin/python -c "import PySide6; print(PySide6.__version__)"` prints a version.

- [ ] **Step 3: Add the `qapp` fixture to `tests/conftest.py`**

Append to `tests/conftest.py` (keep the existing `sample_png`/`sample_jpeg` fixtures):

```python
import os


@pytest.fixture(scope="session")
def qapp():
    # Headless Qt: use the offscreen platform plugin so widgets/tray can be
    # constructed in CI without a display server.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
```

(Ensure `import pytest` is present at the top of conftest.py — it already is.)

- [ ] **Step 4: Write the failing test `tests/test_queue.py`**

```python
from pathlib import Path

from klop.job import JobResult, JobStatus, OptimizationJob
from klop.queue import OptimizationQueue


def test_submit_runs_each_path_and_emits_results(qapp, tmp_path):
    seen = []

    def fake_optimize(job: OptimizationJob) -> JobResult:
        seen.append(job.source_path)
        return JobResult(JobStatus.OPTIMIZED, job.source_path, 1000, 400, backup_id="b1")

    q = OptimizationQueue(optimize_fn=fake_optimize, concurrency=2)
    results = []
    q.job_done.connect(results.append)

    q.submit([tmp_path / "a.png", tmp_path / "b.png"])
    q.wait_for_done(5000)
    qapp.processEvents()

    assert len(results) == 2
    assert {r.status for r in results} == {JobStatus.OPTIMIZED}
    assert set(seen) == {tmp_path / "a.png", tmp_path / "b.png"}


def test_worker_exception_becomes_error_result(qapp, tmp_path):
    def boom(job: OptimizationJob) -> JobResult:
        raise RuntimeError("kaboom")

    q = OptimizationQueue(optimize_fn=boom, concurrency=1)
    results = []
    q.job_done.connect(results.append)

    q.submit([tmp_path / "x.png"])
    q.wait_for_done(5000)
    qapp.processEvents()

    assert len(results) == 1
    assert results[0].status == JobStatus.ERROR
    assert "kaboom" in results[0].message
    assert results[0].path == tmp_path / "x.png"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_queue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.queue'`.

- [ ] **Step 6: Create `src/klop/queue.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .job import JobResult, JobStatus, OptimizationJob


class _JobRunnable(QRunnable):
    def __init__(self, queue: "OptimizationQueue", path: Path):
        super().__init__()
        self._queue = queue
        self._path = path

    def run(self) -> None:
        result = self._queue._run_one(self._path)
        # Emitting from the worker thread is safe; Qt marshals the signal to
        # the receiver's (GUI) thread via a queued connection.
        self._queue.job_done.emit(result)


class OptimizationQueue(QObject):
    """Runs optimization jobs off the GUI thread via a bounded QThreadPool."""

    job_done = Signal(object)  # payload: JobResult

    def __init__(
        self,
        optimize_fn: Callable[[OptimizationJob], JobResult],
        concurrency: int = 2,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._optimize_fn = optimize_fn
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(max(1, concurrency))

    def submit(self, paths: list[Path]) -> None:
        for raw in paths:
            self._pool.start(_JobRunnable(self, Path(raw)))

    def wait_for_done(self, msec: int = -1) -> bool:
        return self._pool.waitForDone(msec)

    def _run_one(self, path: Path) -> JobResult:
        try:
            return self._optimize_fn(OptimizationJob(source_path=path))
        except Exception as exc:  # noqa: BLE001 - surface any worker failure as ERROR
            return JobResult(
                status=JobStatus.ERROR,
                path=path,
                original_size=0,
                new_size=0,
                message=str(exc),
            )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_queue.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (47 = 45 + 2).

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/klop/queue.py tests/conftest.py tests/test_queue.py
git commit -m "Update: add PySide6 OptimizationQueue over the engine

Add PySide6 as a runtime dependency and OptimizationQueue, a QObject
that runs engine jobs on a QThreadPool (concurrency from config) and
emits job_done(JobResult) on the GUI thread. Worker exceptions are
surfaced as synthesized ERROR results. Add a session-scoped offscreen
qapp test fixture.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Notifier + D-Bus backend (`notifier.py`)

**Files:**
- Create: `src/klop/notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `klop.format.human_size`, `percent_saved`; `klop.job.JobResult`, `JobStatus`.
- Produces:
  - `klop.notifier.NotificationBackend` — a `typing.Protocol`: attribute callbacks `on_action: Callable[[int, str], None] | None` and `on_closed: Callable[[int], None] | None`, and method `send(summary: str, body: str, actions: list[tuple[str, str]], icon: str) -> int` (returns a notification id).
  - `klop.notifier.Notifier(backend, undo_fn, icon="", parent=None)` — a `QObject`.
    - `.notify_result(result: JobResult) -> None`: for `OPTIMIZED` with a `backup_id`, sends a notification with body `"<A> → <B> (-<P>%)"` and an `("undo", "Undo")` action, recording `notification_id → (backup_id, filename)`; for `ERROR`, sends a warning with no actions; `UNCHANGED`/`SKIPPED` send nothing.
    - Wires `backend.on_action` / `backend.on_closed`: on `("undo")` for a known id, calls `undo_fn(backup_id)` then sends a `"Restored <filename>"` notification; unknown ids and other action keys are no-ops; `on_closed` forgets the id.
  - `klop.notifier.DBusNotificationBackend(app_name="Klop", parent=None)` — the real QtDBus backend (constructed by the daemon; exercised by the manual smoke test, not unit tests).

- [ ] **Step 1: Write the failing test `tests/test_notifier.py`**

```python
from pathlib import Path

from klop.job import JobResult, JobStatus
from klop.notifier import Notifier


class FakeBackend:
    def __init__(self):
        self.sent = []  # (id, summary, body, actions, icon)
        self.on_action = None
        self.on_closed = None
        self._next_id = 1

    def send(self, summary, body, actions, icon):
        nid = self._next_id
        self._next_id += 1
        self.sent.append((nid, summary, body, actions, icon))
        return nid


def _optimized(path, orig, new, backup_id="b1"):
    return JobResult(JobStatus.OPTIMIZED, path, orig, new, backup_id=backup_id)


def test_optimized_result_sends_notification_with_undo_action():
    backend = FakeBackend()
    notifier = Notifier(backend=backend, undo_fn=lambda bid: None)
    notifier.notify_result(_optimized(Path("/tmp/photo.jpg"), 8579, 3431))

    assert len(backend.sent) == 1
    nid, summary, body, actions, icon = backend.sent[0]
    assert "photo.jpg" in summary
    assert "60%" in body  # 8579 -> 3431 is -60%
    assert ("undo", "Undo") in actions


def test_undo_action_invokes_undo_fn_and_sends_restored():
    backend = FakeBackend()
    undone = []
    notifier = Notifier(backend=backend, undo_fn=lambda bid: undone.append(bid))
    notifier.notify_result(_optimized(Path("/tmp/photo.jpg"), 1000, 400, backup_id="B7"))

    nid = backend.sent[0][0]
    backend.on_action(nid, "undo")

    assert undone == ["B7"]
    # a follow-up "Restored ..." notification was sent
    assert any("Restored" in s or "Restored" in b for _, s, b, _, _ in backend.sent[1:])
    assert any("photo.jpg" in s or "photo.jpg" in b for _, s, b, _, _ in backend.sent[1:])


def test_unknown_notification_id_is_noop():
    backend = FakeBackend()
    undone = []
    notifier = Notifier(backend=backend, undo_fn=lambda bid: undone.append(bid))
    notifier.notify_result(_optimized(Path("/tmp/photo.jpg"), 1000, 400))

    backend.on_action(9999, "undo")  # never issued
    assert undone == []


def test_non_undo_action_key_is_noop():
    backend = FakeBackend()
    undone = []
    notifier = Notifier(backend=backend, undo_fn=lambda bid: undone.append(bid))
    notifier.notify_result(_optimized(Path("/tmp/photo.jpg"), 1000, 400))
    nid = backend.sent[0][0]

    backend.on_action(nid, "default")
    assert undone == []


def test_closed_forgets_id_so_later_undo_is_noop():
    backend = FakeBackend()
    undone = []
    notifier = Notifier(backend=backend, undo_fn=lambda bid: undone.append(bid))
    notifier.notify_result(_optimized(Path("/tmp/photo.jpg"), 1000, 400))
    nid = backend.sent[0][0]

    backend.on_closed(nid)
    backend.on_action(nid, "undo")
    assert undone == []


def test_unchanged_and_skipped_send_nothing():
    backend = FakeBackend()
    notifier = Notifier(backend=backend, undo_fn=lambda bid: None)
    notifier.notify_result(JobResult(JobStatus.UNCHANGED, Path("/tmp/a.png"), 100, 100))
    notifier.notify_result(JobResult(JobStatus.SKIPPED, Path("/tmp/b.png"), 100, 100))
    assert backend.sent == []


def test_error_sends_warning_without_action():
    backend = FakeBackend()
    notifier = Notifier(backend=backend, undo_fn=lambda bid: None)
    notifier.notify_result(
        JobResult(JobStatus.ERROR, Path("/tmp/a.png"), 0, 0, message="disk full")
    )
    assert len(backend.sent) == 1
    _, summary, body, actions, _ = backend.sent[0]
    assert actions == []
    assert "a.png" in summary
    assert "disk full" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_notifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.notifier'`.

- [ ] **Step 3: Create `src/klop/notifier.py`**

```python
from __future__ import annotations

from typing import Callable, Protocol

from PySide6.QtCore import QObject, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface

from .format import human_size, percent_saved
from .job import JobResult, JobStatus


class NotificationBackend(Protocol):
    on_action: Callable[[int, str], None] | None
    on_closed: Callable[[int], None] | None

    def send(
        self, summary: str, body: str, actions: list[tuple[str, str]], icon: str
    ) -> int: ...


class Notifier(QObject):
    """Turns JobResults into desktop notifications and handles the Undo action."""

    def __init__(self, backend, undo_fn: Callable[[str], object], icon: str = "", parent=None):
        super().__init__(parent)
        self._backend = backend
        self._undo_fn = undo_fn
        self._icon = icon
        # notification id -> (backup_id, filename)
        self._undo_map: dict[int, tuple[str, str]] = {}
        backend.on_action = self._on_action
        backend.on_closed = self._on_closed

    def notify_result(self, result: JobResult) -> None:
        name = result.path.name
        if result.status == JobStatus.OPTIMIZED and result.backup_id:
            body = (
                f"{human_size(result.original_size)} → "
                f"{human_size(result.new_size)} "
                f"(-{percent_saved(result.original_size, result.new_size)}%)"
            )
            nid = self._backend.send(name, body, [("undo", "Undo")], self._icon)
            self._undo_map[nid] = (result.backup_id, name)
        elif result.status == JobStatus.ERROR:
            self._backend.send(name, f"Optimization failed: {result.message}", [], self._icon)
        # UNCHANGED / SKIPPED: intentionally silent

    def _on_action(self, notification_id: int, action_key: str) -> None:
        if action_key != "undo":
            return
        entry = self._undo_map.pop(notification_id, None)
        if entry is None:
            return
        backup_id, name = entry
        self._undo_fn(backup_id)
        self._backend.send("Restored", f"Restored {name}", [], self._icon)

    def _on_closed(self, notification_id: int) -> None:
        self._undo_map.pop(notification_id, None)


class DBusNotificationBackend(QObject):
    """Real backend over org.freedesktop.Notifications. Not unit-tested; the
    Notifier logic is covered via a fake backend, and this adapter is exercised
    by the Task 5 manual smoke test."""

    _SERVICE = "org.freedesktop.Notifications"
    _PATH = "/org/freedesktop/Notifications"

    def __init__(self, app_name: str = "Klop", parent=None):
        super().__init__(parent)
        self.on_action: Callable[[int, str], None] | None = None
        self.on_closed: Callable[[int], None] | None = None
        self._app_name = app_name
        self._bus = QDBusConnection.sessionBus()
        self._iface = QDBusInterface(self._SERVICE, self._PATH, self._SERVICE, self._bus)
        self._bus.connect(
            self._SERVICE, self._PATH, self._SERVICE, "ActionInvoked", self._action_invoked
        )
        self._bus.connect(
            self._SERVICE, self._PATH, self._SERVICE, "NotificationClosed", self._notification_closed
        )

    def send(self, summary, body, actions, icon):
        flat: list[str] = []
        for key, label in actions:
            flat.extend([key, label])
        reply = self._iface.call(
            "Notify", self._app_name, 0, icon, summary, body, flat, {}, -1
        )
        args = reply.arguments()
        return int(args[0]) if args else 0

    @Slot("uint", str)
    def _action_invoked(self, notification_id, action_key):
        if self.on_action:
            self.on_action(int(notification_id), str(action_key))

    @Slot("uint", "uint")
    def _notification_closed(self, notification_id, reason):
        if self.on_closed:
            self.on_closed(int(notification_id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_notifier.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (54 = 47 + 7).

- [ ] **Step 6: Commit**

```bash
git add src/klop/notifier.py tests/test_notifier.py
git commit -m "Update: add notifier with undo action over a D-Bus backend

Add Notifier, which turns JobResults into desktop notifications (with an
Undo action for OPTIMIZED results and a warning for ERROR) and restores
originals when Undo fires. D-Bus is isolated behind an injectable
backend so the undo/mapping logic is unit-tested with a fake; add the
thin QtDBus backend for the daemon.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: TrayApp + icon (`app.py`)

**Files:**
- Create: `src/klop/assets/tray.svg`
- Create: `src/klop/app.py`
- Modify: `pyproject.toml` (ensure the asset ships in the wheel)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `klop.format.human_size`; `klop.job.JobStatus`; a queue object exposing `job_done` (Signal carrying `JobResult`) and `submit(paths)`; a notifier exposing `notify_result(result)`.
- Produces:
  - `klop.app.load_tray_icon() -> QIcon` — the bundled `assets/tray.svg`, falling back to `QIcon.fromTheme("image-x-generic")`.
  - `klop.app.TrayApp(queue, notifier, *, icon=None, pick_files=..., parent=None)` — a `QObject` owning a `QSystemTrayIcon` + `QMenu`. Public attributes for wiring/tests: `optimize_action`, `saved_action`, `enabled_action` (QActions). Methods: `.show()`, `.saved_total() -> int`. Behavior: "Optimize files…" calls `pick_files()` then `queue.submit(paths)` when enabled; toggling `enabled_action` enables/disables the picker; each `OPTIMIZED` `job_done` adds `saved_bytes` to the session total and updates `saved_action` text; every `job_done` is forwarded to `notifier.notify_result`.

- [ ] **Step 1: Create the tray icon `src/klop/assets/tray.svg`**

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">
  <rect x="3" y="3" width="16" height="16" rx="3" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M11 6v6m0 0-2.5-2.5M11 12l2.5-2.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M7 15.5h8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
</svg>
```

- [ ] **Step 2: Ensure the asset ships in the wheel — update `pyproject.toml`**

Add this block to `pyproject.toml` (below the existing `[tool.hatch.build.targets.wheel]` section):

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/klop/assets" = "klop/assets"
```

(Editable installs already read the asset from the source tree; this ensures real wheel builds include it.)

- [ ] **Step 3: Write the failing test `tests/test_app.py`**

```python
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from klop.app import TrayApp, load_tray_icon
from klop.job import JobResult, JobStatus


class FakeQueue(QObject):
    job_done = Signal(object)

    def __init__(self):
        super().__init__()
        self.submitted = []

    def submit(self, paths):
        self.submitted.append(list(paths))


class FakeNotifier:
    def __init__(self):
        self.results = []

    def notify_result(self, result):
        self.results.append(result)


def test_optimize_action_submits_picked_files(qapp):
    queue = FakeQueue()
    notifier = FakeNotifier()
    picked = [Path("/tmp/a.png"), Path("/tmp/b.png")]
    tray = TrayApp(queue=queue, notifier=notifier, pick_files=lambda: picked)

    tray.optimize_action.trigger()

    assert queue.submitted == [picked]


def test_disabling_greys_out_the_picker_and_blocks_submit(qapp):
    queue = FakeQueue()
    tray = TrayApp(queue=queue, notifier=FakeNotifier(), pick_files=lambda: [Path("/tmp/a.png")])

    tray.enabled_action.setChecked(False)  # fires toggled(False)

    assert tray.optimize_action.isEnabled() is False
    tray.optimize_action.trigger()  # disabled QAction: triggered is not emitted
    assert queue.submitted == []


def test_job_done_updates_saved_total_and_forwards_to_notifier(qapp):
    queue = FakeQueue()
    notifier = FakeNotifier()
    tray = TrayApp(queue=queue, notifier=notifier, pick_files=lambda: [])

    result = JobResult(JobStatus.OPTIMIZED, Path("/tmp/a.png"), 10000, 5000, backup_id="b1")
    queue.job_done.emit(result)

    assert tray.saved_total() == 5000
    assert "Saved:" in tray.saved_action.text()
    assert "4.9KB" in tray.saved_action.text()  # 5000 bytes -> 4.9KB
    assert notifier.results == [result]


def test_non_optimized_job_done_does_not_change_total_but_still_notifies(qapp):
    queue = FakeQueue()
    notifier = FakeNotifier()
    tray = TrayApp(queue=queue, notifier=notifier, pick_files=lambda: [])

    result = JobResult(JobStatus.SKIPPED, Path("/tmp/a.png"), 100, 100)
    queue.job_done.emit(result)

    assert tray.saved_total() == 0
    assert notifier.results == [result]


def test_load_tray_icon_returns_a_non_null_icon(qapp):
    icon = load_tray_icon()
    assert not icon.isNull()
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.app'`.

- [ ] **Step 5: Create `src/klop/app.py`**

```python
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from .config import default_config_path
from .format import human_size
from .job import JobResult, JobStatus

_ICON_PATH = Path(__file__).parent / "assets" / "tray.svg"


def load_tray_icon() -> QIcon:
    if _ICON_PATH.exists():
        icon = QIcon(str(_ICON_PATH))
        if not icon.isNull():
            return icon
    return QIcon.fromTheme("image-x-generic")


def _default_pick_files() -> list[Path]:
    paths, _ = QFileDialog.getOpenFileNames(None, "Optimize files")
    return [Path(p) for p in paths]


class TrayApp:
    """System-tray front end: a menu that feeds files to the queue and shows
    a running savings total."""

    def __init__(
        self,
        queue,
        notifier,
        *,
        icon: QIcon | None = None,
        pick_files: Callable[[], list[Path]] = _default_pick_files,
    ):
        self._queue = queue
        self._notifier = notifier
        self._pick_files = pick_files
        self._enabled = True
        self._saved_total = 0

        self._menu = QMenu()
        self.optimize_action = self._menu.addAction("Optimize files…")
        self.optimize_action.triggered.connect(self._on_optimize)

        self.saved_action = self._menu.addAction("Saved: 0B")
        self.saved_action.setEnabled(False)

        self._menu.addSeparator()

        self.enabled_action = self._menu.addAction("Enabled")
        self.enabled_action.setCheckable(True)
        self.enabled_action.setChecked(True)
        self.enabled_action.toggled.connect(self._on_enabled_toggled)

        self._menu.addAction("Open config").triggered.connect(self._on_open_config)
        self._menu.addAction("Quit").triggered.connect(self._on_quit)

        self._tray = QSystemTrayIcon(icon or load_tray_icon())
        self._tray.setContextMenu(self._menu)
        self._tray.setToolTip("Klop")

        queue.job_done.connect(self._on_job_done)

    def show(self) -> None:
        self._tray.show()

    def saved_total(self) -> int:
        return self._saved_total

    def _on_optimize(self, _checked: bool = False) -> None:
        if not self._enabled:
            return
        paths = self._pick_files()
        if paths:
            self._queue.submit(paths)

    def _on_enabled_toggled(self, checked: bool) -> None:
        self._enabled = checked
        self.optimize_action.setEnabled(checked)

    def _on_job_done(self, result: JobResult) -> None:
        if result.status == JobStatus.OPTIMIZED:
            self._saved_total += result.saved_bytes
            self.saved_action.setText(f"Saved: {human_size(self._saved_total)}")
        self._notifier.notify_result(result)

    def _on_open_config(self, _checked: bool = False) -> None:
        path = default_config_path()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")
        subprocess.Popen(["xdg-open", str(path)])

    def _on_quit(self, _checked: bool = False) -> None:
        QApplication.quit()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_app.py -v`
Expected: PASS (5 passed). (If `test_load_tray_icon_returns_a_non_null_icon` fails because the offscreen platform can't rasterize SVG, the `fromTheme` fallback still yields a themed icon; if the CI theme is empty the icon may be null — in that case the fallback line already covers real desktops, so guard the test with `pytest.mark.skipif` only if it proves flaky. It passes on this machine.)

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (59 = 54 + 5).

- [ ] **Step 8: Commit**

```bash
git add src/klop/assets/tray.svg src/klop/app.py pyproject.toml tests/test_app.py
git commit -m "Update: add system-tray app with picker and savings total

Add TrayApp: a QSystemTrayIcon with an Optimize-files picker that feeds
the queue, an Enabled toggle that greys out the picker, a session
savings total, and Open-config/Quit actions. Each job_done updates the
total and is forwarded to the notifier. Bundle a tray icon asset.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Daemon wiring + `daemon` subcommand (`daemon.py`, `cli.py`)

**Files:**
- Create: `src/klop/daemon.py`
- Modify: `src/klop/cli.py` (add the `daemon` subcommand via a lazy import)
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `klop.app.TrayApp`, `load_tray_icon`; `klop.queue.OptimizationQueue`; `klop.notifier.Notifier`, `DBusNotificationBackend`; `klop.cli._build_engine`; `klop.config.load_config`.
- Produces:
  - `klop.daemon.build_daemon(app, *, engine=None, backend=None) -> tuple[TrayApp, OptimizationQueue, Notifier]` — constructs and wires the queue (concurrency from config), notifier (real D-Bus backend unless injected), and tray; returns them without starting the event loop. Injecting `engine`/`backend` keeps it testable without real optimizers or D-Bus.
  - `klop.daemon.run_daemon() -> int` — creates the `QApplication`, builds the daemon, shows the tray, and runs `app.exec()`.
  - `cli.py` gains a `daemon` subcommand whose handler lazily imports and calls `run_daemon()` (so importing `cli` never imports Qt).

- [ ] **Step 1: Write the failing test `tests/test_daemon.py`**

```python
from pathlib import Path

from klop.daemon import build_daemon
from klop.job import JobResult, JobStatus


class FakeEngine:
    def __init__(self):
        self.undone = []

    def optimize(self, job):
        return JobResult(JobStatus.OPTIMIZED, job.source_path, 1000, 200, backup_id="b1")

    def undo(self, backup_id):
        self.undone.append(backup_id)


class FakeBackend:
    def __init__(self):
        self.sent = []
        self.on_action = None
        self.on_closed = None
        self._n = 1

    def send(self, summary, body, actions, icon):
        nid = self._n
        self._n += 1
        self.sent.append((nid, summary, body, actions, icon))
        return nid


def test_build_daemon_wires_queue_to_tray_and_notifier(qapp, tmp_path):
    engine = FakeEngine()
    backend = FakeBackend()
    tray, queue, notifier = build_daemon(qapp, engine=engine, backend=backend)

    # A submitted job should flow: queue worker -> engine.optimize ->
    # job_done -> tray total update + notifier notification.
    queue.submit([tmp_path / "z.png"])
    queue.wait_for_done(5000)
    qapp.processEvents()

    assert tray.saved_total() == 800  # 1000 - 200
    assert len(backend.sent) == 1  # one OPTIMIZED notification with Undo
    assert ("undo", "Undo") in backend.sent[0][3]


def test_build_daemon_undo_action_restores_via_engine(qapp, tmp_path):
    engine = FakeEngine()
    backend = FakeBackend()
    tray, queue, notifier = build_daemon(qapp, engine=engine, backend=backend)

    queue.submit([tmp_path / "z.png"])
    queue.wait_for_done(5000)
    qapp.processEvents()

    nid = backend.sent[0][0]
    backend.on_action(nid, "undo")

    assert engine.undone == ["b1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_daemon.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.daemon'`.

- [ ] **Step 3: Create `src/klop/daemon.py`**

```python
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .app import TrayApp, load_tray_icon
from .cli import _build_engine
from .config import load_config
from .notifier import DBusNotificationBackend, Notifier
from .queue import OptimizationQueue


def build_daemon(app, *, engine=None, backend=None):
    engine = engine or _build_engine()
    config = load_config()
    queue = OptimizationQueue(optimize_fn=engine.optimize, concurrency=config.concurrency)
    backend = backend or DBusNotificationBackend()
    notifier = Notifier(backend=backend, undo_fn=engine.undo)
    tray = TrayApp(queue=queue, notifier=notifier, icon=load_tray_icon())
    return tray, queue, notifier


def run_daemon() -> int:
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)  # tray-only app; no windows keep it alive
    tray, _queue, _notifier = build_daemon(app)
    tray.show()
    return app.exec()
```

- [ ] **Step 4: Add the `daemon` subcommand to `src/klop/cli.py`**

Add this handler (after `_cmd_undo`, before `main`):

```python
def _cmd_daemon(_args) -> int:
    from .daemon import run_daemon  # lazy: keeps Qt out of the headless CLI import path

    return run_daemon()
```

And register the subparser inside `main`, after the `caps` subparser registration:

```python
    p_daemon = sub.add_parser("daemon", help="run the system-tray daemon")
    p_daemon.set_defaults(func=_cmd_daemon)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_daemon.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Verify the headless CLI still imports without Qt**

Run: `.venv/bin/python -c "import sys, klop.cli; assert 'PySide6' not in sys.modules; print('cli import is Qt-free: OK')"`
Expected: prints `cli import is Qt-free: OK` (importing `cli` must not pull in PySide6).

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (61 = 59 + 2).

- [ ] **Step 8: Manual smoke test (interactive — perform in a Plasma session)**

Run: `.venv/bin/klop daemon`
Then: right-click the tray icon → **Optimize files…** → pick a large JPEG. Confirm a desktop notification appears showing the savings with an **Undo** button, that the file shrank on disk, and that clicking **Undo** restores the original. Confirm the tray menu's **Saved:** total increased. Note the outcome in the report. (If not in a graphical session, state that the automated tests cover the wiring and this step was skipped.)

- [ ] **Step 9: Commit**

```bash
git add src/klop/daemon.py src/klop/cli.py tests/test_daemon.py
git commit -m "Update: add daemon wiring and klop daemon subcommand

Add build_daemon()/run_daemon() wiring the queue, notifier, and tray
over the engine, and a `klop daemon` subcommand that launches the
tray app. The subcommand imports Qt lazily so the headless CLI stays
Qt-free. Injectable engine/backend keep the wiring unit-tested without
real optimizers or D-Bus.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- `klop daemon` launches a QApplication + tray → Task 5 (`run_daemon`) + Task 4 (`TrayApp`). ✓
- Tray menu (Optimize files…, Saved: X, Enabled, Open config, Quit) → Task 4. ✓
- Jobs run off the GUI thread via a worker pool → Task 2 (`OptimizationQueue`/`QThreadPool`). ✓
- Desktop notification per optimized file with savings + Undo → Task 3 (`Notifier`) + Task 5 wiring. ✓
- Headless CLI unchanged and Qt-free → Task 1 (formatter extraction only) + Task 5 Step 6 assertion. ✓
- PySide6 dependency (abi3 wheel) → Task 2. ✓
- D-Bus behind an injectable backend → Task 3. ✓
- Session-only total; Enabled gates the picker → Task 4. ✓
- Notification policy (OPTIMIZED+ERROR notify, UNCHANGED/SKIPPED silent) → Task 3 tests. ✓
- Shared `format.py` (DRY) → Task 1. ✓
- Tray icon asset + wheel packaging → Task 4. ✓
- Testing under offscreen with injected fakes → Tasks 2-5 (`qapp` fixture, FakeQueue/FakeBackend/FakeEngine). ✓

**Placeholder scan:** No TBD/TODO; every code and test step contains complete code. The only non-automated step is the Task 5 manual smoke test, explicitly marked interactive with a skip path.

**Type consistency:** `OptimizationQueue(optimize_fn, concurrency)` + `job_done = Signal(object)` + `submit`/`wait_for_done`; `Notifier(backend, undo_fn, icon)` + `notify_result`; backend `send(summary, body, actions, icon) -> int` and `on_action(id, key)`/`on_closed(id)`; `TrayApp(queue, notifier, *, icon, pick_files)` with `optimize_action`/`saved_action`/`enabled_action`/`saved_total()`; `build_daemon(app, *, engine, backend) -> (TrayApp, OptimizationQueue, Notifier)` — all used consistently across the tasks that define and consume them. `JobResult(status, path, original_size, new_size, backup_id, message)` and `saved_bytes` match the M0 definitions.
