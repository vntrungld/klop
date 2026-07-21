# Media format expansion — design

**Date:** 2026-07-15
**Status:** Approved (brainstorm), pending spec review
**Goal:** Match Clop's optimizer coverage. Wire up optimizers for every media
type `clop-kde` already *detects* but does not yet *optimize* — GIF, WebP, PDF,
Video, and HEIC — including conversions that change the file extension
(non-mp4 video→MP4). HEIC was implemented then dropped; see "HEIC dropped".

## Background

Detection ([`media.py`](../../../src/clop_kde/media.py)) already recognizes PNG,
JPEG, GIF, WebP, HEIC, Video (mp4/mov/mkv/webm), and PDF. But the optimizer
registry ([`optimizers.py`](../../../src/clop_kde/optimizers.py) `_REGISTRY`)
only handles **PNG** (`pngquant`) and **JPEG** (`jpegoptim`). Everything else is
detected and then skipped with "no optimizer available".

The original design's filetype→optimizer table
([`2026-07-13-clop-kde-design.md`](2026-07-13-clop-kde-design.md)) already
specifies the target tools; this spec implements them (the deferred "M6"
milestone plus GIF/WebP).

### Key architectural constraint

The current engine ([`engine.py:50-91`](../../../src/clop_kde/engine.py))
optimizes **in place, keeping the same extension**: it makes a temp file with
`suffix=source.suffix`, runs the optimizer, and does an atomic
`os.replace(tmp, source)`. This works for same-extension optimization but breaks
for *conversions* (MOV/MKV/WebM→MP4) where the output extension differs and
the original file must be removed. The design below extends the engine to handle
both cases.

## Design

### 1. Extend `Optimizer` with an output extension

Add one field to the `Optimizer` dataclass in
[`optimizers.py`](../../../src/clop_kde/optimizers.py):

```python
output_ext: str | None = None   # None → keep source suffix; ".jpg"/".mp4" → convert
```

Existing optimizers (`PNGQUANT`, `JPEGOPTIM`) keep `output_ext=None` and behave
exactly as before. Builders are unchanged in signature — the engine owns file
routing.

### 2. Register the new optimizers

Add builders + registry entries. First available tool per media type wins
(existing `select_optimizer` logic unchanged).

| MediaType | Tool | Command (essence) | `output_ext` | Config knob |
|---|---|---|---|---|
| `GIF`   | `gifsicle` | `gifsicle -O3 [--lossy=N] -o out -- in` | `None` | `gif_lossy` |
| `WEBP`  | `cwebp` (fallback `vips`) | `cwebp -q Q -mt -o out -- in` | `None` | `webp_quality` |
| `PDF`   | `gs` | `gs -sDEVICE=pdfwrite -dPDFSETTINGS=/<setting> -dNOPAUSE -dBATCH -sOutputFile=out in` | `None` | `pdf_setting` |
| `VIDEO` | `ffmpeg` | `ffmpeg -i in -c:v libx264 -crf N -preset P -c:a aac -y out` | **`.mp4`** | `video_crf`, `video_codec`, `video_preset` |
| ~~`HEIC`~~ | ~~`vips`~~ | **REMOVED — see "HEIC dropped" below** | — | — |

### HEIC dropped (2026-07-21, after end-to-end testing)

HEIC was implemented as specified (`vips` → `.jpg`) and then **removed**, because
end-to-end testing with real binaries showed it can never fire. HEIC is already
an efficient codec, so there is no size win available:

| Attempt | Source | Result |
|---|---|---|
| HEIC → JPEG Q=80 | 9,043 B | 29,402 B (**+225%**) |
| HEIC → JPEG Q=80 | 114,010 B | 181,020 B (**+59%**) |
| HEIC → HEIC Q=90 | 114,010 B | 568,227 B (+398%) |
| HEIC → HEIC Q=80 | 114,010 B | 349,652 B (+207%) |
| HEIC → HEIC Q=50 | 114,010 B | 113,997 B (−13 B) |

Converting to JPEG always inflates. Re-encoding HEIC→HEIC only shrinks when the
chosen Q is below the source's, which is not knowable (a fixed Q=80 tripled a
Q≈50 source). Since the engine only replaces when the result is smaller, every
outcome is rejected — the registry entry was dead code that merely made users
believe their HEICs were being processed.

`.heic`/`.heif` still detect as `MediaType.HEIC` and now report
`skipped: no optimizer available for heic`. Converting HEIC for
**compatibility** (many Linux apps cannot open it) remains a legitimate but
*separate* feature: an explicitly-invoked convert, not an auto-optimize path
gated on size.

Removing HEIC also retired a latent capability bug: `capabilities.py` only
checks `shutil.which("vips")`, so a system with `vips` but without `libheif`
(observed on the dev machine) would have run vips, failed, and reported
"optimizer produced no smaller output" instead of a useful hint. With HEIC
gone, `vips` serves only as the WebP fallback, where the heif module is
irrelevant.

Notes:
- **Video** normalizes every container to `.mp4`/H.264. An `.mp4` input keeps
  the `.mp4` extension (in-place path); `.mkv`/`.mov`/`.webm` convert to `.mp4`.
- `gif_lossy = 0` means lossless (`-O3` only); a positive value adds
  `--lossy=N`.
- `cwebp` reads PNG/JPEG/TIFF; recompressing an existing `.webp` may need the
  `vips` fallback. VERIFIED 2026-07-21: cwebp 1.6 does accept `.webp` input,
  so the static [cwebp, vips] ordering is sufficient; no runtime fallback needed.
- All tools are optional and capability-detected; already listed in
  `capabilities.KNOWN_TOOLS`. A type whose tool is absent is skipped with the
  existing "install <tool>" hint.

### 3. Engine: convert-aware replace

Modify `Engine.optimize` in [`engine.py`](../../../src/clop_kde/engine.py):

1. `out_suffix = optimizer.output_ext or source.suffix`.
2. Create the temp file with `suffix=out_suffix` (not `source.suffix`) so
   `ffmpeg`/`vips` select the right muxer/encoder from the extension.
3. Run optimizer; keep the existing exit-code / empty-output / `min_bytes_saved`
   checks (comparing original vs. produced output).
4. **Same-extension path** (`out_suffix.lower() == source.suffix.lower()`):
   unchanged — backup, chmod/chown, `os.replace(tmp, source)`.
5. **Convert path** (extensions differ):
   - `backup_id = backup_store.backup(source)`
   - `dest = _dedup(source.with_suffix(out_suffix))` — never clobber an
     unrelated existing file.
   - chmod/chown the temp to match `source`.
   - `os.replace(tmp, dest)` (atomic within the same directory).
   - `source.unlink()` — remove the now-converted original.
   - Return `JobResult(status=OPTIMIZED, path=dest, ..., backup_id=backup_id)`
     so history/overlay reference the new file.
6. Failure handling on the convert path mirrors the same-extension path
   (`ERROR` result, temp cleaned up in `finally`). If `os.replace` succeeds but
   `source.unlink()` fails, the job still succeeded (dest written, backup taken)
   — log best-effort, do not fail the job.

### 4. Shared dedup helper

Promote `_dedup` from [`webfetch.py:65`](../../../src/clop_kde/webfetch.py) into
a shared module (`paths.py`) and import it in both `webfetch.py` and
`engine.py`. Behavior unchanged (`photo.jpg` → `photo-1.jpg` → …).

### 5. Config

Add fields to `Config` in [`config.py`](../../../src/clop_kde/config.py):

```python
webp_quality: int = 80
gif_lossy: int = 0              # 0 = lossless (-O3 only)
pdf_setting: str = "ebook"     # screen | ebook | printer | prepress
video_crf: int = 28
video_codec: str = "libx264"
video_preset: str = "medium"
```

Load / save / `config get|set` coercion are field-driven (iterate
`dataclasses.fields`), so these surface automatically with no code change.
`pdf_setting` is validated against the allowed set at command-build time
(fallback to `ebook` on an unknown value).

**Plasmoid form** ([`ConfigGeneral.qml`](../../../src/clop_kde/plasmoid_pkg/contents/ui/ConfigGeneral.qml))
hardcodes one control per field, so each new knob needs a matching control plus
its entry in the save/load JS. Add: WebP quality (SpinBox), GIF lossy (SpinBox),
PDF setting (ComboBox), video CRF/codec/preset (SpinBox + two fields).

### 6. Testing (TDD)

- `select_optimizer` returns the new tool for each media type when its
  capability is present, and `None` when absent.
- Engine same-extension optimize for GIF/WebP/PDF still replaces in place
  (fake runner writing a smaller file).
- Engine **convert**: fake runner writes a smaller `.jpg`/`.mp4`; assert the
  original (`.mkv`) is deleted, `dest` exists with the new extension,
  `result.path == dest`, backup created, and `undo` restores the original file
  at its original path.
- Dedup on convert: when `clip.mp4` already exists, a `clip.mkv` convert yields
  `clip-1.mp4` and leaves the pre-existing `clip.mp4` untouched.
- Convert produces a *larger* output → `UNCHANGED`, original kept, no new file.
- Tool absent → `SKIPPED` with the install hint (existing mechanism).

## Out of scope (YAGNI)

- No chained convert-then-optimize (e.g. vips→jpegoptim); the vips JPEG quality
  knob is good enough for now.
- No `gifski` (GIF) or `oxipng` (PNG lossless) fallbacks this pass.
- No overlay/notification UI changes — they already render `JobResult.path` and
  sizes generically.

## Affected files

- `src/clop_kde/optimizers.py` — `output_ext` field, new builders + registry.
- `src/clop_kde/engine.py` — convert-aware replace path.
- `src/clop_kde/config.py` — new knobs.
- `src/clop_kde/paths.py` — new; shared `_dedup`.
- `src/clop_kde/webfetch.py` — import shared `_dedup`.
- `src/clop_kde/plasmoid_pkg/contents/ui/ConfigGeneral.qml` — new form controls.
- `tests/` — new optimizer + engine-convert coverage.
