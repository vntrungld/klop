"""Run ffmpeg while reporting how far through the input it is.

``-progress pipe:1`` makes ffmpeg print ``key=value`` blocks (``out_time_us``
among them) about twice a second; the input's length comes from the
``Duration:`` line of its banner. stderr is merged into stdout so one pipe
carries both and a full stderr buffer can't stall the encode.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def progress_command(cmd: list[str]) -> list[str]:
    """``cmd`` with ffmpeg's machine-readable progress on stdout."""
    return [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]


def parse_duration(line: str) -> float | None:
    """Seconds from a banner line like ``Duration: 00:01:02.50, start: ...``."""
    m = _DURATION_RE.search(line)
    if m is None:
        return None
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def parse_out_time(line: str) -> float | None:
    """Seconds encoded so far from an ``out_time_us=...`` progress line."""
    key, _, value = line.strip().partition("=")
    if key != "out_time_us":
        return None
    try:
        return int(value) / 1_000_000
    except ValueError:  # "N/A" before the first frame
        return None


def run_ffmpeg(cmd: list[str], on_progress: Callable[[float], None]) -> int:
    """Run ffmpeg ``cmd``, calling ``on_progress`` with 0.0–1.0; return its exit code."""
    proc = subprocess.Popen(
        progress_command(cmd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    duration = None
    assert proc.stdout is not None
    for line in proc.stdout:
        if duration is None:
            duration = parse_duration(line)
            continue
        done = parse_out_time(line)
        if done is not None and duration > 0:
            on_progress(min(max(done / duration, 0.0), 1.0))
    return proc.wait()
