# Media Format Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up optimizers for every media type `klop` already detects but does not yet optimize — GIF, WebP, PDF, Video, HEIC — including extension-changing conversions (HEIC→JPEG, non-mp4 video→MP4).

**Architecture:** Add same-extension optimizers (gifsicle, cwebp/vips, ghostscript) that drop straight into the existing in-place engine, plus convert optimizers (ffmpeg→mp4, vips→jpg) enabled by a new `output_ext` field on `Optimizer` and a convert-aware replace branch in the engine that backs up the original, writes a non-clobbering destination, and drops the source.

**Tech Stack:** Python 3.14, PySide6 (unused here), pytest; external CLIs `gifsicle`, `cwebp`, `vips`, `gs`, `ffmpeg` (all optional, capability-detected).

## Global Constraints

- **Commit message format:** first line `{Action}: {desc}` where Action ∈ {Update, Fix, WIP, Hotfix}, imperative, <72 chars; blank line; body wrapped at 72; `Co-Authored-By: Claude <noreply@anthropic.com>` trailer. Commit with `git -c user.name='Klop' -c user.email='vn.trungld@gmail.com' commit`.
- **All external tools are optional** and resolved via `capabilities.detect_capabilities`. A media type whose tool is absent must fall through to the existing `SKIPPED` result with the "install <tool>" hint — never crash.
- **Engine safety invariants (unchanged):** write to a temp file in the source's directory; only replace when the result is smaller by at least `config.min_bytes_saved`; back up the original before replacing; atomic `os.replace` within the same directory.
- **Test runner:** `pytest` from the repo root. All new pure-Python logic is tested with fake runners (no real CLI needed); real-CLI tests are guarded with `@pytest.mark.skipif(not shutil.which(...))`.

---

## File Structure

- `src/klop/config.py` — add six optimizer knobs (Task 1).
- `src/klop/paths.py` — **new**; shared `dedup(path)` helper (Task 2).
- `src/klop/webfetch.py` — import shared `dedup`, drop the private copy (Task 2).
- `src/klop/optimizers.py` — new builders + registry entries; `output_ext` field (Tasks 3, 4).
- `src/klop/engine.py` — convert-aware replace branch (Task 5).
- `src/klop/plasmoid_pkg/contents/ui/ConfigGeneral.qml` — form controls for new knobs (Task 6).
- Tests: `tests/test_config.py`, `tests/test_paths.py` (new), `tests/test_optimizers.py`, `tests/test_engine.py`.

---

## Task 1: Config knobs for the new optimizers

**Files:**
- Modify: `src/klop/config.py:10-20` (the `Config` dataclass)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` gains fields `webp_quality: int = 80`, `gif_lossy: int = 0`, `pdf_setting: str = "ebook"`, `video_crf: int = 28`, `video_codec: str = "libx264"`, `video_preset: str = "medium"`. Load/save/`config get|set` coercion is field-driven and needs no other change.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_new_optimizer_knobs_have_defaults():
    from klop.config import Config
    c = Config()
    assert c.webp_quality == 80
    assert c.gif_lossy == 0
    assert c.pdf_setting == "ebook"
    assert c.video_crf == 28
    assert c.video_codec == "libx264"
    assert c.video_preset == "medium"


def test_new_knobs_round_trip_through_toml(tmp_path):
    from klop.config import Config, save_config, load_config
    path = tmp_path / "config.toml"
    save_config(Config(webp_quality=70, video_crf=30, pdf_setting="screen"), path)
    loaded = load_config(path)
    assert loaded.webp_quality == 70
    assert loaded.video_crf == 30
    assert loaded.pdf_setting == "screen"


def test_new_knobs_apply_overrides():
    from klop.config import Config, apply_overrides
    c = apply_overrides(Config(), {"video_crf": "23", "video_codec": "libx265"})
    assert c.video_crf == 23
    assert c.video_codec == "libx265"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_new_optimizer_knobs_have_defaults -v`
Expected: FAIL with `AttributeError` / `TypeError` (fields not defined).

- [ ] **Step 3: Add the fields**

In `src/klop/config.py`, extend the `Config` dataclass (insert after `jpeg_max_quality`):

```python
@dataclass(frozen=True)
class Config:
    png_lossy: bool = True
    pngquant_quality: tuple[int, int] = (65, 80)
    jpeg_max_quality: int = 80
    webp_quality: int = 80
    gif_lossy: int = 0                 # 0 = lossless (-O3 only)
    pdf_setting: str = "ebook"         # screen | ebook | printer | prepress
    video_crf: int = 28
    video_codec: str = "libx264"
    video_preset: str = "medium"
    min_bytes_saved: int = 1
    concurrency: int = 2
    backup_retention_days: int = 7
    backup_max_bytes: int = 500 * 1024 * 1024
    clipboard_watch: bool = True
    web_drop_dir: str = "~/Pictures/Klop"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (new tests plus all existing config tests).

- [ ] **Step 5: Commit**

```bash
git add src/klop/config.py tests/test_config.py
git -c user.name='Klop' -c user.email='vn.trungld@gmail.com' commit -m "Update: add config knobs for gif/webp/pdf/video optimizers

Add webp_quality, gif_lossy, pdf_setting, video_crf, video_codec, and
video_preset to Config. Load/save/config-set coercion is field-driven
so no loader change is needed.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Shared `dedup` path helper

**Files:**
- Create: `src/klop/paths.py`
- Modify: `src/klop/webfetch.py:65-73` (remove `_dedup`), `:98` (call site)
- Test: `tests/test_paths.py`

**Interfaces:**
- Produces: `klop.paths.dedup(path: Path) -> Path` — returns `path` if it does not exist, else the first free `"{stem}-{i}{suffix}"` (i from 1). Consumed by `webfetch` (Task 2) and `engine` (Task 5).

- [ ] **Step 1: Write the failing test**

Create `tests/test_paths.py`:

```python
from klop.paths import dedup


def test_dedup_returns_path_when_free(tmp_path):
    p = tmp_path / "a.jpg"
    assert dedup(p) == p


def test_dedup_suffixes_when_taken(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    assert dedup(tmp_path / "a.jpg") == tmp_path / "a-1.jpg"


def test_dedup_skips_multiple_collisions(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "a-1.jpg").write_bytes(b"x")
    assert dedup(tmp_path / "a.jpg") == tmp_path / "a-2.jpg"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'klop.paths'`.

- [ ] **Step 3: Create the shared helper**

Create `src/klop/paths.py`:

```python
from __future__ import annotations

from pathlib import Path


def dedup(path: Path) -> Path:
    """Return `path` if free, else the first available '{stem}-{i}{suffix}'."""
    if not path.exists():
        return path
    i = 1
    while True:
        cand = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1
```

- [ ] **Step 4: Point `webfetch` at the shared helper**

In `src/klop/webfetch.py`, delete the `_dedup` function (lines 65-73) and add an import near the top (with the other `from .` imports):

```python
from .paths import dedup
```

Change the call site (was line 98) from:

```python
    target = _dedup(dest_dir / _filename_for(final_url or url, mtype))
```

to:

```python
    target = dedup(dest_dir / _filename_for(final_url or url, mtype))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_paths.py tests/test_webfetch.py -v`
Expected: PASS (new paths tests plus existing webfetch tests still green).

- [ ] **Step 6: Commit**

```bash
git add src/klop/paths.py src/klop/webfetch.py tests/test_paths.py
git -c user.name='Klop' -c user.email='vn.trungld@gmail.com' commit -m "Update: extract shared dedup path helper

Promote webfetch._dedup to klop.paths.dedup so the engine's
convert path can reuse the same non-clobbering rename logic.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Same-extension optimizers (GIF, WebP, PDF)

**Files:**
- Modify: `src/klop/optimizers.py` (new builders + `_REGISTRY` entries)
- Test: `tests/test_optimizers.py`

**Interfaces:**
- Consumes: `Optimizer` dataclass and `Config` (Task 1 fields).
- Produces: module-level `GIFSICLE`, `CWEBP`, `VIPS_WEBP`, `GS` optimizers; `_REGISTRY` gains `GIF: [GIFSICLE]`, `WEBP: [CWEBP, VIPS_WEBP]`, `PDF: [GS]`. All keep `output_ext` defaulting to `None` (same-extension). `select_optimizer`/`expected_tools` unchanged in signature.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_optimizers.py` (extend the import from `klop.optimizers` to include `GIFSICLE, CWEBP, VIPS_WEBP, GS`):

```python
def test_gifsicle_command_shape():
    from klop.optimizers import GIFSICLE
    cfg = Config(gif_lossy=0)
    cmd = GIFSICLE.build_command(Path("/in.gif"), Path("/out.gif"), cfg)
    assert cmd[0] == "gifsicle"
    assert "-O3" in cmd
    assert "--lossy=0" not in " ".join(cmd)   # lossless when gif_lossy == 0
    assert cmd[cmd.index("-o") + 1] == "/out.gif"
    assert cmd[-1] == "/in.gif"
    assert GIFSICLE.use_stdout is False


def test_gifsicle_lossy_flag_when_enabled():
    from klop.optimizers import GIFSICLE
    cmd = GIFSICLE.build_command(Path("/in.gif"), Path("/out.gif"), Config(gif_lossy=30))
    assert "--lossy=30" in cmd


def test_cwebp_command_shape():
    from klop.optimizers import CWEBP
    cmd = CWEBP.build_command(Path("/in.webp"), Path("/out.webp"), Config(webp_quality=70))
    assert cmd[0] == "cwebp"
    assert cmd[cmd.index("-q") + 1] == "70"
    assert cmd[cmd.index("-o") + 1] == "/out.webp"
    assert cmd[-1] == "/in.webp"


def test_vips_webp_command_shape():
    from klop.optimizers import VIPS_WEBP
    cmd = VIPS_WEBP.build_command(Path("/in.webp"), Path("/out.webp"), Config(webp_quality=65))
    assert cmd[0] == "vips"
    assert cmd[1] == "copy"
    assert cmd[2] == "/in.webp"
    assert cmd[3].startswith("/out.webp[")
    assert "Q=65" in cmd[3]


def test_gs_command_shape():
    from klop.optimizers import GS
    cmd = GS.build_command(Path("/in.pdf"), Path("/out.pdf"), Config(pdf_setting="screen"))
    assert cmd[0] == "gs"
    assert "-dPDFSETTINGS=/screen" in cmd
    assert "-sOutputFile=/out.pdf" in cmd
    assert cmd[-1] == "/in.pdf"


def test_gs_unknown_setting_falls_back_to_ebook():
    from klop.optimizers import GS
    cmd = GS.build_command(Path("/in.pdf"), Path("/out.pdf"), Config(pdf_setting="bogus"))
    assert "-dPDFSETTINGS=/ebook" in cmd


def test_select_new_same_ext_optimizers():
    from klop.optimizers import GIFSICLE, CWEBP, VIPS_WEBP, GS
    caps = {"gifsicle": "/x", "cwebp": "/x", "vips": "/x", "gs": "/x"}
    assert select_optimizer(MediaType.GIF, caps, Config()) is GIFSICLE
    assert select_optimizer(MediaType.WEBP, caps, Config()) is CWEBP
    assert select_optimizer(MediaType.PDF, caps, Config()) is GS
    # cwebp missing → vips fallback for WebP
    assert select_optimizer(MediaType.WEBP, {"vips": "/x"}, Config()) is VIPS_WEBP
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_optimizers.py -v`
Expected: FAIL with `ImportError` (names not defined).

- [ ] **Step 3: Implement the builders and register them**

In `src/klop/optimizers.py`, add the builders after `_jpegoptim_cmd`:

```python
def _gifsicle_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    cmd = ["gifsicle", "-O3"]
    if cfg.gif_lossy > 0:
        cmd.append(f"--lossy={cfg.gif_lossy}")
    cmd += ["-o", str(out), "--", str(inp)]
    return cmd


def _cwebp_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    return ["cwebp", "-q", str(cfg.webp_quality), "-mt", "-o", str(out), str(inp)]


def _vips_webp_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    return ["vips", "copy", str(inp), f"{out}[Q={cfg.webp_quality},strip]"]


_PDF_SETTINGS = {"screen", "ebook", "printer", "prepress"}


def _gs_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    setting = cfg.pdf_setting if cfg.pdf_setting in _PDF_SETTINGS else "ebook"
    return [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS=/{setting}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={out}",
        str(inp),
    ]
```

Add the optimizer instances after `JPEGOPTIM`:

```python
GIFSICLE = Optimizer("gifsicle", "gifsicle", _gifsicle_cmd, use_stdout=False)
CWEBP = Optimizer("cwebp", "cwebp", _cwebp_cmd, use_stdout=False)
VIPS_WEBP = Optimizer("vips", "vips", _vips_webp_cmd, use_stdout=False)
GS = Optimizer("gs", "gs", _gs_cmd, use_stdout=False)
```

Extend `_REGISTRY`:

```python
_REGISTRY: dict[MediaType, list[Optimizer]] = {
    MediaType.PNG: [PNGQUANT],
    MediaType.JPEG: [JPEGOPTIM],
    MediaType.GIF: [GIFSICLE],
    MediaType.WEBP: [CWEBP, VIPS_WEBP],
    MediaType.PDF: [GS],
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_optimizers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/klop/optimizers.py tests/test_optimizers.py
git -c user.name='Klop' -c user.email='vn.trungld@gmail.com' commit -m "Update: add gifsicle/cwebp/vips/gs same-extension optimizers

Register GIF (gifsicle -O3), WebP (cwebp, vips fallback), and PDF
(ghostscript) optimizers. All keep the source extension, so they run
through the existing in-place engine path unchanged.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Convert optimizers + `output_ext` field (Video, HEIC)

**Files:**
- Modify: `src/klop/optimizers.py` (add `output_ext` to `Optimizer`; new builders + registry)
- Test: `tests/test_optimizers.py`

**Interfaces:**
- Produces: `Optimizer` gains `output_ext: str | None = None`. New optimizers `FFMPEG` (`output_ext=".mp4"`) and `VIPS_HEIC` (`output_ext=".jpg"`). `_REGISTRY` gains `VIDEO: [FFMPEG]`, `HEIC: [VIPS_HEIC]`. Consumed by the engine (Task 5) to decide the convert branch.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_optimizers.py`:

```python
def test_ffmpeg_command_shape_and_output_ext():
    from klop.optimizers import FFMPEG
    cfg = Config(video_crf=30, video_codec="libx264", video_preset="fast")
    cmd = FFMPEG.build_command(Path("/in.mkv"), Path("/out.mp4"), cfg)
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-i") + 1] == "/in.mkv"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-crf") + 1] == "30"
    assert cmd[cmd.index("-preset") + 1] == "fast"
    assert cmd[-1] == "/out.mp4"          # output is the last arg
    assert FFMPEG.output_ext == ".mp4"


def test_vips_heic_command_shape_and_output_ext():
    from klop.optimizers import VIPS_HEIC
    cmd = VIPS_HEIC.build_command(Path("/in.heic"), Path("/out.jpg"), Config(jpeg_max_quality=75))
    assert cmd[0] == "vips"
    assert cmd[1] == "copy"
    assert cmd[2] == "/in.heic"
    assert cmd[3].startswith("/out.jpg[")
    assert "Q=75" in cmd[3]
    assert VIPS_HEIC.output_ext == ".jpg"


def test_existing_optimizers_default_output_ext_none():
    assert PNGQUANT.output_ext is None
    assert JPEGOPTIM.output_ext is None


def test_select_convert_optimizers():
    from klop.optimizers import FFMPEG, VIPS_HEIC
    caps = {"ffmpeg": "/x", "vips": "/x"}
    assert select_optimizer(MediaType.VIDEO, caps, Config()) is FFMPEG
    assert select_optimizer(MediaType.HEIC, caps, Config()) is VIPS_HEIC
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_optimizers.py -v`
Expected: FAIL with `ImportError` / `AttributeError` (no `output_ext`, names missing).

- [ ] **Step 3: Add the field and the convert optimizers**

In `src/klop/optimizers.py`, add `output_ext` to the dataclass:

```python
@dataclass(frozen=True)
class Optimizer:
    name: str
    tool: str
    _builder: Callable[[Path, Path, Config], list[str]]
    use_stdout: bool = False
    output_ext: str | None = None   # None = keep source suffix; ".jpg"/".mp4" = convert

    def build_command(self, inp: Path, out: Path, cfg: Config) -> list[str]:
        return self._builder(inp, out, cfg)
```

Add the builders (after `_gs_cmd`):

```python
def _ffmpeg_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(inp),
        "-c:v",
        cfg.video_codec,
        "-crf",
        str(cfg.video_crf),
        "-preset",
        cfg.video_preset,
        "-c:a",
        "copy",
        str(out),
    ]


def _vips_heic_cmd(inp: Path, out: Path, cfg: Config) -> list[str]:
    return ["vips", "copy", str(inp), f"{out}[Q={cfg.jpeg_max_quality},strip]"]
```

Add the instances and registry entries:

```python
FFMPEG = Optimizer("ffmpeg", "ffmpeg", _ffmpeg_cmd, use_stdout=False, output_ext=".mp4")
VIPS_HEIC = Optimizer("vips", "vips", _vips_heic_cmd, use_stdout=False, output_ext=".jpg")
```

Add to `_REGISTRY`:

```python
    MediaType.VIDEO: [FFMPEG],
    MediaType.HEIC: [VIPS_HEIC],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_optimizers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/klop/optimizers.py tests/test_optimizers.py
git -c user.name='Klop' -c user.email='vn.trungld@gmail.com' commit -m "Update: add ffmpeg/vips convert optimizers with output_ext

Add an output_ext field to Optimizer and register the two conversions:
video normalizes to .mp4 (ffmpeg H.264) and HEIC converts to .jpg
(vips). The engine reads output_ext to route the convert path.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Engine convert-aware replace path

**Files:**
- Modify: `src/klop/engine.py:50-91` (temp suffix + replace branch)
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `Optimizer.output_ext` (Task 4); `klop.paths.dedup` (Task 2).
- Produces: for a convert optimizer, `Engine.optimize` backs up the source, writes to `dedup(source.with_suffix(output_ext))`, unlinks the original, and returns `JobResult(status=OPTIMIZED, path=<new dest>, backup_id=...)`. Same-extension optimizers behave exactly as before.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_engine.py`. These use a fake ffmpeg-style runner that writes to the output temp (`cmd[-1]`), matching the VIDEO optimizer:

```python
def test_convert_writes_new_extension_and_drops_source(tmp_path):
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"\x1a\x45\xdf\xa3" + b"x" * 5000)  # EBML magic → VIDEO

    def runner(cmd, stdout_path):
        out = Path(cmd[-1])                    # ffmpeg output is the last arg
        assert out.suffix == ".mp4"
        out.write_bytes(b"\x00" * 500)
        return 0

    engine = make_engine(tmp_path, {"ffmpeg": "/usr/bin/ffmpeg"}, runner)
    result = engine.optimize(OptimizationJob(source_path=src))

    assert result.status == JobStatus.OPTIMIZED
    dest = tmp_path / "clip.mp4"
    assert result.path == dest
    assert dest.exists()
    assert not src.exists()                    # original converted away
    assert result.backup_id is not None

    # Undo restores the original .mkv at its original path.
    restored = engine.undo(result.backup_id)
    assert restored == src
    assert src.exists()
    assert len(src.read_bytes()) == 5004


def test_convert_dedups_when_dest_exists(tmp_path):
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"\x1a\x45\xdf\xa3" + b"x" * 5000)
    taken = tmp_path / "clip.mp4"
    taken.write_bytes(b"unrelated")            # pre-existing, must not be clobbered

    def runner(cmd, stdout_path):
        Path(cmd[-1]).write_bytes(b"\x00" * 500)
        return 0

    engine = make_engine(tmp_path, {"ffmpeg": "/usr/bin/ffmpeg"}, runner)
    result = engine.optimize(OptimizationJob(source_path=src))

    assert result.status == JobStatus.OPTIMIZED
    assert result.path == tmp_path / "clip-1.mp4"
    assert taken.read_bytes() == b"unrelated"  # untouched


def test_convert_unchanged_when_not_smaller_keeps_source(tmp_path):
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"\x1a\x45\xdf\xa3" + b"x" * 100)

    def runner(cmd, stdout_path):
        Path(cmd[-1]).write_bytes(b"\x00" * 5000)   # bigger than original
        return 0

    engine = make_engine(tmp_path, {"ffmpeg": "/usr/bin/ffmpeg"}, runner)
    result = engine.optimize(OptimizationJob(source_path=src))

    assert result.status == JobStatus.UNCHANGED
    assert src.exists()                        # original kept
    assert not (tmp_path / "clip.mp4").exists()  # no converted file left behind
    assert result.backup_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_engine.py::test_convert_writes_new_extension_and_drops_source -v`
Expected: FAIL — current engine uses `source.suffix` for the temp and always replaces in place, so `clip.mp4` is never produced.

- [ ] **Step 3: Implement the convert-aware branch**

In `src/klop/engine.py`, add the import near the top (with the other `from .` imports):

```python
from .paths import dedup
```

Replace the body from the temp-file creation through the `return` (current lines 50-91) with:

```python
        out_suffix = optimizer.output_ext or source.suffix
        fd, tmp_name = tempfile.mkstemp(dir=source.parent, suffix=out_suffix)
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
                else:
                    dest = source
                    os.replace(tmp, source)  # atomic within same directory
            except OSError as e:
                return JobResult(
                    JobStatus.ERROR, source, original_size, original_size,
                    message=f"failed to replace {source.name}: {e}",
                )
            return JobResult(
                JobStatus.OPTIMIZED, dest, original_size, new_size,
                backup_id=backup_id,
            )
        finally:
            if tmp.exists():
                tmp.unlink()
```

- [ ] **Step 4: Run the full engine suite to verify pass + no regressions**

Run: `pytest tests/test_engine.py -v`
Expected: PASS — the three new convert tests plus all existing same-extension tests (`test_optimized_replaces_and_backs_up`, `test_unchanged_*`, permission, replace-failure) stay green.

- [ ] **Step 5: Commit**

```bash
git add src/klop/engine.py tests/test_engine.py
git -c user.name='Klop' -c user.email='vn.trungld@gmail.com' commit -m "Update: add convert-aware replace path to engine

When an optimizer declares output_ext, the engine now writes the temp
with the target extension, backs up the original, writes to a
non-clobbering dedup destination, drops the source, and reports the new
path. Same-extension optimizers keep the existing in-place replace.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Plasmoid config form controls

**Files:**
- Modify: `src/klop/plasmoid_pkg/contents/ui/ConfigGeneral.qml`

**Interfaces:**
- Consumes: `klop config get --json` (already emits the new keys after Task 1) and `klop config set key=value`.
- Produces: form controls for `webp_quality`, `gif_lossy`, `pdf_setting`, `video_crf`, `video_codec`, `video_preset`, wired into `saveConfig()` and `Component.onCompleted`.

- [ ] **Step 1: Add the controls to the FormLayout**

In `ConfigGeneral.qml`, insert these after the `jpegMax` SpinBox (after line 61, before the `minSaved` SpinBox):

```qml
        QQC2.SpinBox {
            id: webpQuality
            Kirigami.FormData.label: "WebP quality:"
            from: 1; to: 100
        }
        QQC2.SpinBox {
            id: gifLossy
            Kirigami.FormData.label: "GIF lossy (0 = off):"
            from: 0; to: 200
        }
        QQC2.ComboBox {
            id: pdfSetting
            Kirigami.FormData.label: "PDF quality:"
            model: ["screen", "ebook", "printer", "prepress"]
        }
        QQC2.SpinBox {
            id: videoCrf
            Kirigami.FormData.label: "Video CRF:"
            from: 0; to: 51
        }
        QQC2.TextField {
            id: videoCodec
            Kirigami.FormData.label: "Video codec:"
        }
        QQC2.TextField {
            id: videoPreset
            Kirigami.FormData.label: "Video preset:"
        }
```

- [ ] **Step 2: Wire them into `saveConfig()`**

In the `assigns` array inside `saveConfig()`, add these entries (after the `jpeg_max_quality` line). `video_codec` and `video_preset` are strings, so shell-quote them:

```qml
            "webp_quality=" + webpQuality.value,
            "gif_lossy=" + gifLossy.value,
            "pdf_setting=" + shquote(pdfSetting.currentValue),
            "video_crf=" + videoCrf.value,
            "video_codec=" + shquote(videoCodec.text),
            "video_preset=" + shquote(videoPreset.text),
```

- [ ] **Step 3: Load them in `Component.onCompleted`**

In the JSON callback (after `jpegMax.value = c.jpeg_max_quality;`), add:

```qml
            webpQuality.value = c.webp_quality;
            gifLossy.value = c.gif_lossy;
            pdfSetting.currentIndex = pdfSetting.model.indexOf(c.pdf_setting);
            videoCrf.value = c.video_crf;
            videoCodec.text = c.video_codec;
            videoPreset.text = c.video_preset;
```

- [ ] **Step 4: Validate QML syntax**

Run: `qmllint src/klop/plasmoid_pkg/contents/ui/ConfigGeneral.qml`
Expected: no syntax errors. (If `qmllint` is not installed, skip — it is a lint, not a hard gate; the import warnings for `org.kde.*` modules are expected outside a Plasma session.)

- [ ] **Step 5: Smoke-test the round trip via the CLI backing the form**

`config get|set` have no path flag — they resolve `~/.config/klop/config.toml` from `HOME`, so redirect `HOME` to a temp dir to avoid touching the real config:

```bash
HOME=/tmp/clop-smoke python -m klop.cli config set webp_quality=70 pdf_setting=screen video_codec=libx265
HOME=/tmp/clop-smoke python -m klop.cli config get --json
```
Expected: the JSON includes `"webp_quality": 70`, `"pdf_setting": "screen"`, `"video_codec": "libx265"`.

- [ ] **Step 6: Commit**

```bash
git add src/klop/plasmoid_pkg/contents/ui/ConfigGeneral.qml
git -c user.name='Klop' -c user.email='vn.trungld@gmail.com' commit -m "Update: add plasmoid form controls for new optimizer knobs

Expose webp_quality, gif_lossy, pdf_setting, video_crf, video_codec,
and video_preset in the plasmoid settings form, wired to config
get/set like the existing fields.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run the whole suite:** `pytest -q` — all tests green.
- [ ] **Optional real-tool smoke** (only where the CLI is installed): optimize a sample `.gif`, `.webp`, `.pdf` (same-extension) and a `.mkv`/`.heic` (convert) and confirm the result is smaller / the new extension appears and `undo` restores the original.

---

## Self-review notes

- **Spec coverage:** Optimizer field (§1) → Task 4; new optimizers (§2) → Tasks 3-4; engine convert (§3) → Task 5; shared dedup (§4) → Task 2; config (§5) → Task 1; plasmoid form (§5) → Task 6; tests (§6) → each task. All spec sections mapped.
- **Type consistency:** `dedup` (public) used identically in Tasks 2 and 5; `output_ext` defined in Task 4 and read in Task 5; `Config` field names identical across Tasks 1/3/4/6; `JobResult(status, path, original_size, new_size, backup_id, message)` matches `job.py`.
- **Known limitation (documented, out of scope):** undo restores the original file but does not delete the converted destination; acceptable for this pass.
