# Clop-KDE — In-Progress Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a pending "Optimizing <name>…" overlay card with an indeterminate progress bar whenever any job (file, drop, or clipboard) starts, then replace it with the result (file/drop) or dismiss it (clipboard).

**Architecture:** Add a `job_started` signal to the queue and `started`/`finished` signals to the clipboard watcher; add a pending visual state to `ResultOverlay`; have the `ResultRouter` show the pending card on start and dismiss it on non-OPTIMIZED outcomes; wire it all in `build_daemon`.

**Tech Stack:** Python 3.11+, PySide6 QtWidgets (adds `QProgressBar`, already available). Headless-tested under the offscreen `qapp` fixture. No new dependencies.

## Global Constraints

- **Python 3.11+, PySide6.** The headless CLI stays Qt-free (overlay/queue/clipboard are daemon-only, imported lazily).
- **Indeterminate bar only** — `QProgressBar.setRange(0, 0)`. Image optimizers report no progress; do NOT attempt percentage parsing. (M6 video can later drive a determinate bar.)
- **A pending card is shown for EVERY job, so it must never linger:** file/drop OPTIMIZED replaces it with the result card; ERROR/UNCHANGED/SKIPPED dismiss it; clipboard dismisses it via `finished` (fired on both outcomes).
- **Clipboard result surface is unchanged** (still the desktop notification); the clipboard pending card is transient.
- **`results.py` must stay Qt-free** (no Qt imports) — it passes a `Path` to the overlay, which does the pixmap loading.
- **Commit message format:** first line `{Action}: {desc}` where Action ∈ {Update, Fix, WIP, Hotfix}, imperative, <72 chars; blank line; body; `Co-Authored-By: Claude <noreply@anthropic.com>` trailer. Commit with `git -c user.name='Clop-KDE' -c user.email='vn.trungld@gmail.com' commit`.
- **Dev commands:** `.venv/bin/pytest`. Baseline suite: 102 passing.

## File Structure

```
src/clop_kde/
├── queue.py      # MODIFY: add job_started signal, emit before running the optimizer
├── clipboard.py  # MODIFY: add started/finished signals; emit around a job
├── overlay.py    # MODIFY: add QProgressBar + show_pending + _set_thumbnail; refactor show_result
├── results.py    # MODIFY: add on_job_started; dismiss overlay on non-OPTIMIZED outcomes
└── daemon.py     # MODIFY: wire job_started + watcher started/finished to the overlay
tests/
├── test_queue.py     # MODIFY: add job_started ordering test
├── test_clipboard.py # MODIFY: add started/finished tests
├── test_overlay.py   # MODIFY: add pending-state tests
├── test_results.py   # MODIFY: on_job_started + dismiss-on-non-optimized
└── test_daemon.py    # MODIFY: pending wiring
```

---

## Task 1: Queue `job_started` signal

**Files:**
- Modify: `src/clop_kde/queue.py`
- Test: `tests/test_queue.py`

**Interfaces:**
- Produces: `OptimizationQueue.job_started = Signal(object)` (payload: the source `Path`),
  emitted from the worker thread immediately before running the optimizer, ahead of `job_done`.

- [ ] **Step 1: Write the failing test (append to `tests/test_queue.py`)**

```python
def test_job_started_is_emitted_before_job_done(qapp, tmp_path):
    def fake_optimize(job):
        return JobResult(JobStatus.OPTIMIZED, job.source_path, 1000, 400, backup_id="b1")

    q = OptimizationQueue(optimize_fn=fake_optimize, concurrency=1)
    events = []
    q.job_started.connect(lambda path: events.append(("start", path)))
    q.job_done.connect(lambda result: events.append(("done", result.status)))

    p = tmp_path / "a.png"
    q.submit([p])
    q.wait_for_done(5000)
    qapp.processEvents()

    assert len(events) == 2
    assert events[0] == ("start", p)  # started fires first, with the path
    assert events[1][0] == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_queue.py::test_job_started_is_emitted_before_job_done -v`
Expected: FAIL — `OptimizationQueue` has no attribute `job_started` (AttributeError).

- [ ] **Step 3: Add the signal and emit it in `src/clop_kde/queue.py`**

In `_JobRunnable.run` (currently lines 17-21), emit `job_started` before running:

```python
    def run(self) -> None:
        # Emitting from the worker thread is safe; Qt marshals the signals to
        # the receiver's (GUI) thread via queued connections.
        self._queue.job_started.emit(self._path)
        result = self._queue._run_one(self._path)
        self._queue.job_done.emit(result)
```

And add the signal to the `OptimizationQueue` class, next to `job_done` (line 27):

```python
    job_started = Signal(object)  # payload: source Path
    job_done = Signal(object)  # payload: JobResult
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_queue.py -v`
Expected: PASS (existing queue tests + the new one).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (103 = 102 + 1).

- [ ] **Step 6: Commit**

```bash
git add src/clop_kde/queue.py tests/test_queue.py
git commit -m "Update: emit job_started before running each optimizer

Add OptimizationQueue.job_started(path), emitted from the worker just
before the optimizer runs, so the UI can show an in-progress indicator.
job_done still follows on completion.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Overlay pending state

**Files:**
- Modify: `src/clop_kde/overlay.py`
- Test: `tests/test_overlay.py`

**Interfaces:**
- Produces:
  - `ResultOverlay.progress_bar: QProgressBar` (indeterminate, `setRange(0, 0)`), hidden by default.
  - `ResultOverlay.show_pending(self, title: str, thumbnail_source=None) -> None` — shows a
    "Optimizing <title>…" card: thumbnail (from a `Path`/`str`, `bytes`, or fallback icon),
    the progress bar visible, Undo/Open hidden, savings cleared, NO auto-dismiss timer.
  - `show_result` now hides the progress bar and shows the buttons (restoring from the pending state).

- [ ] **Step 1: Write the failing tests (append to `tests/test_overlay.py`)**

```python
def test_show_pending_shows_progress_and_hides_buttons(qapp):
    overlay = ResultOverlay()
    overlay.show_pending("report.png")
    assert "Optimizing" in overlay.title_label.text()
    assert "report.png" in overlay.title_label.text()
    assert overlay.progress_bar.isVisible()
    assert overlay.progress_bar.minimum() == 0 and overlay.progress_bar.maximum() == 0
    assert not overlay.undo_button.isVisible()
    assert not overlay.open_button.isVisible()
    assert not overlay._timer.isActive()  # a pending card must not auto-dismiss


def test_show_result_after_pending_restores_buttons_and_hides_progress(qapp, tmp_path):
    p = tmp_path / "photo.png"
    _write_png(p)
    overlay = ResultOverlay()
    overlay.show_pending("photo.png")
    overlay.show_result(_result(p))
    assert not overlay.progress_bar.isVisible()
    assert overlay.undo_button.isVisible()
    assert overlay.open_button.isVisible()
    assert "60%" in overlay.savings_label.text()


def test_show_pending_with_png_bytes_thumbnail(qapp, tmp_path):
    p = tmp_path / "photo.png"
    _write_png(p)
    data = p.read_bytes()
    overlay = ResultOverlay()
    overlay.show_pending("Clipboard image", data)  # bytes source
    assert not overlay.thumb_label.pixmap().isNull()
```

(These reuse the existing `_write_png` and `_result` helpers already at the top of test_overlay.py.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_overlay.py -k "pending or after_pending" -v`
Expected: FAIL — `ResultOverlay` has no `progress_bar` / `show_pending` (AttributeError).

- [ ] **Step 3: Edit `src/clop_kde/overlay.py`**

Add `QProgressBar` to the QtWidgets import:

```python
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
```

In `__init__`, after the `savings_label` is created and before `self.undo_button`, add the bar,
and add it to the text column. Replace the layout block (lines 61-77) with:

```python
        self.title_label = QLabel()
        self.savings_label = QLabel()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate / busy
        self.progress_bar.hide()

        self.undo_button = QPushButton("Undo")
        self.open_button = QPushButton("Open")
        self.undo_button.clicked.connect(self._on_undo)
        self.open_button.clicked.connect(self._on_open)

        self.button_row = QHBoxLayout()
        self.button_row.addWidget(self.undo_button)
        self.button_row.addWidget(self.open_button)
        # (M6 downscale buttons are appended to button_row here)

        text_col = QVBoxLayout()
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.savings_label)
        text_col.addWidget(self.progress_bar)
        text_col.addLayout(self.button_row)
```

Add a `_set_thumbnail` helper and a `show_pending` method, and refactor `show_result` to use the
helper and manage the pending/result widget states. Replace `show_result` (lines 87-113) with:

```python
    def _set_thumbnail(self, source) -> None:
        pixmap = QPixmap()
        if isinstance(source, (str, Path)):
            pixmap = QPixmap(str(source))
        elif isinstance(source, (bytes, bytearray)):
            pixmap.loadFromData(bytes(source))
        if pixmap.isNull():
            self.thumb_label.setPixmap(
                QIcon.fromTheme("image-x-generic").pixmap(_THUMB, _THUMB)
            )
        else:
            self.thumb_label.setPixmap(
                pixmap.scaled(
                    _THUMB,
                    _THUMB,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def show_pending(self, title: str, thumbnail_source=None) -> None:
        self._path = None
        self._backup_id = None
        self._set_thumbnail(thumbnail_source)
        self.title_label.setText(f"Optimizing {title}…")
        self.savings_label.clear()
        self.progress_bar.show()
        self.undo_button.hide()
        self.open_button.hide()
        self._timer.stop()  # a pending card stays until the result replaces it
        self._reposition()
        self.show()
        self.raise_()

    def show_result(self, result: JobResult) -> None:
        self._path = Path(result.path)
        self._backup_id = result.backup_id
        self._set_thumbnail(self._path)
        self.title_label.setText(self._path.name)
        self.savings_label.setText(
            f"{human_size(result.original_size)} → "
            f"{human_size(result.new_size)} "
            f"(-{percent_saved(result.original_size, result.new_size)}%)"
        )
        self.progress_bar.hide()
        self.undo_button.show()
        self.open_button.show()
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(_DISMISS_MS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_overlay.py -v`
Expected: PASS — the existing overlay tests (show_result, undo, open, drag mime, dismiss) still
pass after the refactor, plus the 3 new pending tests.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (106 = 103 + 3 new overlay tests). Report the actual count.

- [ ] **Step 6: Commit**

```bash
git add src/clop_kde/overlay.py tests/test_overlay.py
git commit -m "Update: add pending state to the result overlay

Add an indeterminate progress bar and show_pending(title, thumbnail) to
ResultOverlay: an 'Optimizing <name>…' card with the busy bar and the
action buttons hidden, shown while a job runs. show_result now hides the
bar and restores the buttons. Thumbnail loading is shared via a helper
that accepts a path or raw PNG bytes.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Clipboard `started` / `finished` signals

**Files:**
- Modify: `src/clop_kde/clipboard.py`
- Test: `tests/test_clipboard.py`

**Interfaces:**
- Produces:
  - `ClipboardWatcher.started = Signal(object)` (payload: the original PNG bytes) — emitted in
    `_on_changed` right before the worker is dispatched.
  - `ClipboardWatcher.finished = Signal()` — emitted at the end of `_on_result_ready`, for BOTH the
    optimized and the no-gain (None) outcomes. `optimized` still fires only on a real result.

- [ ] **Step 1: Write the failing tests (append to `tests/test_clipboard.py`)**

```python
def test_watcher_emits_started_and_finished_on_optimize(qapp):
    clip = FakeClipboard()
    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=lambda d: _SMALLER)
    events = []
    watcher.started.connect(lambda data: events.append(("started", bytes(data))))
    watcher.finished.connect(lambda: events.append(("finished",)))

    clip.setMimeData(_png_mime(_ORIGINAL))
    watcher.wait_for_done(5000)
    qapp.processEvents()

    assert ("started", _ORIGINAL) in events
    assert ("finished",) in events
    assert events.index(("started", _ORIGINAL)) < events.index(("finished",))


def test_watcher_emits_finished_even_when_no_gain(qapp):
    clip = FakeClipboard()
    watcher = ClipboardWatcher(clipboard=clip, optimize_fn=lambda d: None)  # no gain
    finished = []
    watcher.finished.connect(lambda: finished.append(1))

    clip.setMimeData(_png_mime(_ORIGINAL))
    watcher.wait_for_done(5000)
    qapp.processEvents()

    assert finished == [1]  # finished fires even though nothing was optimized
```

(These reuse the existing `FakeClipboard`, `_png_mime`, `_ORIGINAL`, `_SMALLER` helpers in test_clipboard.py.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_clipboard.py -k "started or no_gain" -v`
Expected: FAIL — `ClipboardWatcher` has no `started` / `finished` signals (AttributeError).

- [ ] **Step 3: Edit `src/clop_kde/clipboard.py`**

Add the two signals to the `ClipboardWatcher` class, next to `optimized` (line 91-92):

```python
    optimized = Signal(object)  # ClipboardResult
    started = Signal(object)  # original PNG bytes (job began)
    finished = Signal()  # job finished (either outcome)
    _result_ready = Signal(object, str, object)  # (original_bytes, digest, optimized|None)
```

In `_on_changed`, emit `started` right before dispatching the worker (after the `_remember`),
replacing the `self._pool.start(...)` line region:

```python
        self._remember(digest)  # mark in-flight before starting the worker so a
        # repeated dataChanged for the same content (e.g. Klipper firing twice
        # per copy) doesn't race a second worker into existence.
        self.started.emit(png)
        self._pool.start(_ClipRunnable(self, png, digest))
```

Restructure `_on_result_ready` (lines 157-168) so `finished` fires on both outcomes:

```python
    def _on_result_ready(self, original: bytes, digest: str, optimized) -> None:
        self._remember(digest)  # don't reprocess this exact input
        if optimized is not None:
            self._remember(content_hash(optimized))
            self._undo_counter += 1
            token = str(self._undo_counter)
            self._undo_store[token] = original
            while len(self._undo_store) > _UNDO_MAX:
                self._undo_store.popitem(last=False)
            self._set_clipboard_png(optimized)
            self.optimized.emit(ClipboardResult(len(original), len(optimized), token))
        self.finished.emit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_clipboard.py -v`
Expected: PASS — existing clipboard tests still pass (the restructure preserves optimize/undo/loop
behavior) plus the 2 new signal tests.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (108 = 106 + 2). Report the actual count.

- [ ] **Step 6: Commit**

```bash
git add src/clop_kde/clipboard.py tests/test_clipboard.py
git commit -m "Update: add started/finished signals to ClipboardWatcher

Emit started(png_bytes) when a clipboard job begins and finished() when
it ends (both the optimized and no-gain outcomes), so the overlay can
show and then clear a transient 'Optimizing…' card. optimized still
fires only on a real result.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Router pending + dismiss-on-non-optimized

**Files:**
- Modify: `src/clop_kde/results.py`
- Test: `tests/test_results.py`

**Interfaces:**
- Consumes: `overlay.show_pending(name, path)`, `overlay.show_result(result)`, `overlay.dismiss()`.
- Produces:
  - `ResultRouter.on_job_started(self, path) -> None` → `overlay.show_pending(Path(path).name, Path(path))`.
  - `on_job_done` now dismisses the overlay on ERROR/UNCHANGED/SKIPPED (so the pending card cannot
    linger); OPTIMIZED still calls `overlay.show_result` (which itself replaces the pending card).

- [ ] **Step 1: Update `tests/test_results.py` (RED)**

Extend the `FakeOverlay` class to record pending + dismiss calls:

```python
class FakeOverlay:
    def __init__(self):
        self.shown = []
        self.pending = []
        self.dismissed = 0

    def show_result(self, result):
        self.shown.append(result)

    def show_pending(self, title, thumbnail_source=None):
        self.pending.append((title, thumbnail_source))

    def dismiss(self):
        self.dismissed += 1
```

Replace `test_error_routes_to_notifier_not_overlay` and `test_unchanged_and_skipped_are_silent`
with versions that account for the pending-card dismissal, and add a started test:

```python
def test_on_job_started_shows_pending(tmp_path):
    tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
    p = tmp_path / "photo.png"
    ResultRouter(tray, overlay, notifier).on_job_started(p)
    assert overlay.pending == [("photo.png", p)]


def test_error_notifies_and_dismisses_pending():
    tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
    result = JobResult(JobStatus.ERROR, Path("/tmp/a.png"), 0, 0, message="disk full")
    ResultRouter(tray, overlay, notifier).on_job_done(result)
    assert notifier.results == [result]
    assert overlay.shown == []  # no result card
    assert overlay.dismissed == 1  # pending card cleared


def test_unchanged_and_skipped_dismiss_pending_silently():
    for status in (JobStatus.UNCHANGED, JobStatus.SKIPPED):
        tray, overlay, notifier = FakeTray(), FakeOverlay(), FakeNotifier()
        ResultRouter(tray, overlay, notifier).on_job_done(
            JobResult(status, Path("/tmp/a.png"), 100, 100)
        )
        assert tray.saved == [] and overlay.shown == [] and notifier.results == []
        assert overlay.dismissed == 1  # pending card cleared, nothing else
```

Leave `test_optimized_routes_to_overlay_and_total_not_notifier` as-is, but add one assertion that
OPTIMIZED does not dismiss (it replaces via show_result):

```python
    assert overlay.dismissed == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_results.py -v`
Expected: FAIL — `ResultRouter` has no `on_job_started`; ERROR/UNCHANGED/SKIPPED don't call
`overlay.dismiss` yet.

- [ ] **Step 3: Rewrite `src/clop_kde/results.py`**

```python
from __future__ import annotations

from pathlib import Path

from .job import JobResult, JobStatus


class ResultRouter:
    """Routes optimization lifecycle events across the tray total, floating overlay,
    and notifier. A pending overlay card is shown while a file/drop job runs, then
    replaced by the result (OPTIMIZED) or dismissed (error/unchanged/skipped)."""

    def __init__(self, tray, overlay, notifier):
        self._tray = tray
        self._overlay = overlay
        self._notifier = notifier

    def on_job_started(self, path) -> None:
        path = Path(path)
        self._overlay.show_pending(path.name, path)

    def on_job_done(self, result: JobResult) -> None:
        if result.status == JobStatus.OPTIMIZED:
            self._tray.record_saved(result.saved_bytes)
            self._overlay.show_result(result)  # replaces the pending card
        elif result.status == JobStatus.ERROR:
            self._notifier.notify_result(result)
            self._overlay.dismiss()
        else:  # UNCHANGED / SKIPPED
            self._overlay.dismiss()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_results.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (109 = 108 + 1 net new results test). Report the actual count.

- [ ] **Step 6: Commit**

```bash
git add src/clop_kde/results.py tests/test_results.py
git commit -m "Update: show pending card on job start; dismiss on non-optimize

Add ResultRouter.on_job_started, which shows the overlay's pending card
for a starting file/drop job, and dismiss the overlay on
error/unchanged/skipped so the pending card never lingers (OPTIMIZED
still replaces it with the result card).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Daemon wiring

**Files:**
- Modify: `src/clop_kde/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `queue.job_started`, `router.on_job_started`, `watcher.started`, `watcher.finished`,
  `overlay.show_pending`, `overlay.dismiss`.
- Produces: `build_daemon` connects `queue.job_started → router.on_job_started`; and, when the
  clipboard watcher exists, `watcher.started → overlay.show_pending("Clipboard image", bytes)` and
  `watcher.finished → overlay.dismiss`.

- [ ] **Step 1: Update `tests/test_daemon.py` (RED)**

Extend the `FakeOverlay` (in test_daemon.py) to record pending + dismiss:

```python
class FakeOverlay:
    def __init__(self):
        self.shown = []
        self.pending = []
        self.dismissed = 0

    def show_result(self, result):
        self.shown.append(result)

    def show_pending(self, title, thumbnail_source=None):
        self.pending.append((title, thumbnail_source))

    def dismiss(self):
        self.dismissed += 1
```

Add two tests:

```python
def test_build_daemon_wires_job_started_to_overlay_pending(qapp, tmp_path):
    overlay = FakeOverlay()
    d = build_daemon(qapp, engine=FakeEngine(), backend=FakeBackend(), overlay=overlay)
    d.queue.job_started.emit(tmp_path / "z.png")
    qapp.processEvents()
    assert overlay.pending and overlay.pending[0][0] == "z.png"


def test_build_daemon_wires_clipboard_started_and_finished_to_overlay(qapp):
    from PySide6.QtCore import QMimeData, QObject, Signal

    class FakeClipboard(QObject):
        dataChanged = Signal()

        def mimeData(self):
            return QMimeData()

        def setMimeData(self, md):
            pass

    overlay = FakeOverlay()
    d = build_daemon(
        qapp, engine=FakeEngine(), backend=FakeBackend(),
        clipboard=FakeClipboard(), overlay=overlay,
    )
    d.watcher.started.emit(b"\x89PNG\r\n\x1a\n" + b"x" * 10)
    d.watcher.finished.emit()
    qapp.processEvents()
    assert overlay.pending and overlay.pending[0][0] == "Clipboard image"
    assert overlay.dismissed == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_daemon.py -k "job_started or clipboard_started" -v`
Expected: FAIL — `build_daemon` does not connect `job_started`, nor `watcher.started`/`finished`.

- [ ] **Step 3: Edit `src/clop_kde/daemon.py`**

After `queue.job_done.connect(router.on_job_done)` (line 43), add the started wiring:

```python
    router = ResultRouter(tray, overlay, notifier)
    queue.job_done.connect(router.on_job_done)
    queue.job_started.connect(router.on_job_started)
```

Inside the `if config.clipboard_watch:` block, after `watcher.optimized.connect(_on_clipboard_optimized)`
(line 74), add the clipboard pending wiring:

```python
        watcher.optimized.connect(_on_clipboard_optimized)
        watcher.started.connect(
            lambda png: overlay.show_pending("Clipboard image", png)
        )
        watcher.finished.connect(overlay.dismiss)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_daemon.py -v`
Expected: PASS (existing daemon tests + the 2 new pending-wiring tests).

- [ ] **Step 5: Confirm the headless CLI is still Qt-free**

Run: `.venv/bin/python -c "import sys, clop_kde.cli; assert 'PySide6' not in sys.modules; print('cli Qt-free: OK')"`
Expected: prints `cli Qt-free: OK`.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (111 = 109 + 2). Report the actual count.

- [ ] **Step 7: Manual smoke test (interactive — perform in a Plasma session)**

Run: `.venv/bin/clop-kde daemon`
Then optimize a file (tray picker) and copy an image. Confirm a floating card shows
"Optimizing <name>…" with the moving busy bar, then swaps to the savings result (file) or
vanishes as the clipboard notification appears (clipboard). (If not in a graphical session, state
that the automated tests cover the wiring and this step was skipped.)

- [ ] **Step 8: Commit**

```bash
git add src/clop_kde/daemon.py tests/test_daemon.py
git commit -m "Update: wire the in-progress overlay card into the daemon

Connect queue.job_started to the router's pending card and the clipboard
watcher's started/finished signals to the overlay's show_pending/dismiss,
so every job shows an 'Optimizing…' card while it runs.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Pending overlay card (indeterminate bar, buttons hidden) → Task 2 (`show_pending` + `progress_bar`). ✓
- Shown for file/drop on start → Task 1 (`job_started`) + Task 4 (`on_job_started`) + Task 5 (wiring). ✓
- Shown for clipboard on start → Task 3 (`started`) + Task 5 (wiring). ✓
- File/drop OPTIMIZED replaces pending with result; ERROR/UNCHANGED/SKIPPED dismiss → Task 4. ✓
- Clipboard pending dismissed via `finished` (both outcomes); result still notifies → Task 3 + Task 5 (clipboard notification unchanged). ✓
- Indeterminate only (`setRange(0,0)`) → Task 2. ✓
- `results.py` stays Qt-free → Task 4 (passes `Path`, no Qt import). ✓
- CLI stays Qt-free → Task 5 Step 5. ✓

**Placeholder scan:** No TBD/TODO; every code and test step is complete. The only non-automated step is the Task 5 interactive smoke test, explicitly marked with a skip path.

**Type consistency:** `queue.job_started = Signal(object)` (Path); `ClipboardWatcher.started = Signal(object)` (bytes) / `finished = Signal()`; `ResultOverlay.show_pending(title, thumbnail_source)` + `progress_bar` + `_set_thumbnail(source)`; `ResultRouter.on_job_started(path)` + `on_job_done` dismiss branches — all used consistently across the tasks that define and consume them.
