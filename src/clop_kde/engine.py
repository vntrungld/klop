from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

from .backup import BackupStore
from .config import Config
from .job import JobResult, JobStatus, OptimizationJob
from .media import detect_media_type
from .optimizers import expected_tools, select_optimizer


def _default_runner(cmd: list[str], stdout_path: Path | None) -> int:
    """Run cmd; if stdout_path is set, redirect stdout into it. Returns exit code."""
    if stdout_path is not None:
        with open(stdout_path, "wb") as out:
            proc = subprocess.run(cmd, stdout=out, stderr=subprocess.DEVNULL)
    else:
        proc = subprocess.run(cmd, stderr=subprocess.DEVNULL)
    return proc.returncode


class Engine:
    def __init__(self, config: Config, backup_store: BackupStore, capabilities, runner=None):
        self.config = config
        self.backup_store = backup_store
        self.capabilities = capabilities
        self._runner = runner or _default_runner

    def optimize(self, job: OptimizationJob) -> JobResult:
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

        fd, tmp_name = tempfile.mkstemp(dir=source.parent, suffix=source.suffix)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            cmd = optimizer.build_command(source, tmp, self.config)
            stdout_path = tmp if optimizer.use_stdout else None
            code = self._runner(cmd, stdout_path)

            if code != 0 or not tmp.exists() or tmp.stat().st_size == 0:
                return JobResult(
                    JobStatus.UNCHANGED, source, original_size, original_size,
                    message="optimizer produced no smaller output",
                )

            new_size = tmp.stat().st_size
            if original_size - new_size < self.config.min_bytes_saved:
                return JobResult(
                    JobStatus.UNCHANGED, source, original_size, new_size,
                    message="already optimal",
                )

            try:
                backup_id = self.backup_store.backup(source)
                source_stat = source.stat()
                os.chmod(tmp, stat.S_IMODE(source_stat.st_mode))
                try:
                    os.chown(tmp, source_stat.st_uid, source_stat.st_gid)
                except (PermissionError, OSError):
                    pass  # best-effort; not fatal when unprivileged
                os.replace(tmp, source)  # atomic within same directory
            except OSError as e:
                return JobResult(
                    JobStatus.ERROR, source, original_size, original_size,
                    message=f"failed to replace {source.name}: {e}",
                )
            return JobResult(
                JobStatus.OPTIMIZED, source, original_size, new_size,
                backup_id=backup_id,
            )
        finally:
            if tmp.exists():
                tmp.unlink()

    def undo(self, backup_id: str) -> Path:
        return self.backup_store.restore(backup_id)
