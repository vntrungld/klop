from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from .backup import BackupStore
from .config import Config
from .ffprogress import run_ffmpeg
from .job import JobResult, JobStatus, OptimizationJob
from .media import detect_media_type
from .optimizers import expected_tools, select_optimizer
from .paths import dedup


def _default_runner(cmd: list[str], stdout_path: Path | None) -> int:
    """Run cmd; if stdout_path is set, redirect stdout into it. Returns exit code."""
    if stdout_path is not None:
        with open(stdout_path, "wb") as out:
            proc = subprocess.run(cmd, stdout=out, stderr=subprocess.DEVNULL)
    else:
        proc = subprocess.run(cmd, stderr=subprocess.DEVNULL)
    return proc.returncode


class Engine:
    def __init__(
        self,
        config: Config,
        backup_store: BackupStore,
        capabilities,
        runner=None,
        progress_runner=None,
    ):
        self.config = config
        self.backup_store = backup_store
        self.capabilities = capabilities
        self._runner = runner or _default_runner
        # (cmd, on_progress) -> exit code, for optimizers that report progress.
        self._progress_runner = progress_runner or run_ffmpeg

    def optimize(
        self, job: OptimizationJob, on_progress: Callable[[float], None] | None = None
    ) -> JobResult:
        """Optimize one file. ``on_progress`` gets 0.0–1.0 while an optimizer
        that can report it (ffmpeg) runs; image tools finish without calls."""
        source = Path(job.source_path)
        media_type = job.media_type or detect_media_type(source)
        original_size = source.stat().st_size

        optimizer = select_optimizer(media_type, self.capabilities, self.config)
        if optimizer is None:
            tools = expected_tools(media_type)
            tool_hint = f" (install {tools[0]})" if tools else ""
            return JobResult(
                status=JobStatus.SKIPPED,
                path=source,
                original_size=original_size,
                new_size=original_size,
                message=f"no optimizer available for {media_type.value}{tool_hint}",
            )

        out_suffix = optimizer.output_ext or source.suffix
        fd, tmp_name = tempfile.mkstemp(dir=source.parent, suffix=out_suffix)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            cmd = optimizer.build_command(source, tmp, self.config)
            stdout_path = tmp if optimizer.use_stdout else None
            if on_progress is not None and optimizer.reports_progress:
                code = self._progress_runner(cmd, on_progress)
            else:
                code = self._runner(cmd, stdout_path)

            if code != 0 or not tmp.exists() or tmp.stat().st_size == 0:
                return JobResult(
                    JobStatus.UNCHANGED,
                    source,
                    original_size,
                    original_size,
                    message="optimizer produced no smaller output",
                )

            new_size = tmp.stat().st_size
            if original_size - new_size < self.config.min_bytes_saved:
                return JobResult(
                    JobStatus.UNCHANGED,
                    source,
                    original_size,
                    new_size,
                    message="already optimal",
                )

            is_convert = out_suffix.lower() != source.suffix.lower()
            try:
                backup_id = self.backup_store.backup(source)
                source_stat = source.stat()
                os.chmod(tmp, stat.S_IMODE(source_stat.st_mode))
                try:
                    os.chown(tmp, source_stat.st_uid, source_stat.st_gid)
                except (PermissionError, OSError):
                    pass  # best-effort; not fatal when unprivileged
                if is_convert:
                    dest = dedup(source.with_suffix(out_suffix))
                    os.replace(tmp, dest)  # atomic within same directory
                    try:
                        source.unlink()  # drop the now-converted original
                    except OSError:
                        pass  # dest written and backed up; leftover source is non-fatal
                    try:
                        # So undo can clean up the file this convert created.
                        self.backup_store.record_conversion(backup_id, dest, new_size)
                    except (OSError, KeyError):
                        pass  # undo still restores the original; it just leaves dest
                else:
                    dest = source
                    os.replace(tmp, source)  # atomic within same directory
            except OSError as e:
                return JobResult(
                    JobStatus.ERROR,
                    source,
                    original_size,
                    original_size,
                    message=f"failed to replace {source.name}: {e}",
                )
            return JobResult(
                JobStatus.OPTIMIZED,
                dest,
                original_size,
                new_size,
                backup_id=backup_id,
            )
        finally:
            if tmp.exists():
                tmp.unlink()

    def undo(self, backup_id: str) -> Path:
        return self.backup_store.restore(backup_id)
