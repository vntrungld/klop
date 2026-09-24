"""Per-run progress state the panel widget polls.

The widget starts ``klop optimize`` through Plasma's executable data source,
which only reports back once the process exits. So each run also keeps a
one-line JSON file under ``$XDG_RUNTIME_DIR/klop/progress/<pid>.json`` that the
widget reads while jobs are in flight; runs started from Dolphin show up there
too. The file is removed when the run ends.

State written by ``klop optimize``::

    {"name": "b.mp4", "done": 1, "total": 3, "percent": 55,
     "pending": [{"name": "b.mp4", "state": "running", "percent": 65},
                 {"name": "c.mp4", "state": "queued", "percent": -1}]}

``percent`` at the top is the whole run; per file it is -1 when unknown
(queued, or an image tool that reports nothing).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def progress_dir() -> Path:
    override = os.environ.get("KLOP_PROGRESS_DIR")
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(runtime) / "klop" / "progress"


class ProgressFile:
    def __init__(self, directory: Path | None = None):
        self.path = (directory or progress_dir()) / f"{os.getpid()}.json"

    def write(self, state: dict) -> None:
        """Replace the run's state with ``state`` (one JSON line). Best-effort:
        progress must never fail an optimize."""
        line = json.dumps(state)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(line + "\n")
            os.replace(tmp, self.path)  # the widget never sees a half-written file
        except OSError:
            pass

    def remove(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass
