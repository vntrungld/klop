import json
import os

from klop.progress import ProgressFile, progress_dir


def test_progress_dir_uses_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("KLOP_PROGRESS_DIR", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert progress_dir() == tmp_path / "klop" / "progress"


def test_progress_file_writes_one_json_line_per_pid_and_removes(tmp_path):
    pf = ProgressFile(tmp_path)
    state = {"name": "clip.mp4", "done": 1, "total": 3, "percent": 50, "pending": []}
    pf.write(state)

    assert pf.path == tmp_path / f"{os.getpid()}.json"
    assert json.loads(pf.path.read_text()) == state
    assert [p.name for p in tmp_path.iterdir()] == [pf.path.name]  # no temp left behind

    pf.remove()
    assert not pf.path.exists()
    pf.remove()  # idempotent
