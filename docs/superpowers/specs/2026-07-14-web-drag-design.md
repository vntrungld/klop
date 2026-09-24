# Klop — Web-Image Drag Design Spec

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan
**Sub-project D of the applet direction.** Builds on Sub-project C (the Klop plasmoid and its
`klop` CLI shell-out model), the M0 engine/backup, and the history store. Adds the ability
to drag an image **from a web browser** onto the Klop panel icon and have it downloaded,
optimized, saved, and copied to the clipboard.

## Summary

Today the plasmoid's drop handler keeps only local `file://` paths, so an image dragged from a
browser (which arrives as an `http(s)://` URL, not a file) is silently ignored. This sub-project
adds a new Qt-free CLI command `klop optimize-url <url>` that downloads a remote image,
optimizes it (in place, with a backup, reusing the existing `Engine`), saves it to a
configurable folder, and copies the optimized result to the clipboard. The plasmoid's
`onDropped` gains a branch: `file://` drops keep calling `optimize` (unchanged); `http(s)://`
drops call `optimize-url`.

## Goals

- Drag an image from a browser onto the Klop icon → it is downloaded, optimized, **saved** to
  `~/Pictures/Klop` (configurable), **and copied to the clipboard**.
- The download+optimize+save+clipboard+history+notify logic lives in the Qt-free CLI
  (`optimize-url`), so it is testable in Python and needs no running daemon.
- Robust, safe fetching: http/https only, timeout, size cap, real-image validation by magic
  bytes, filename sanitization, never overwrite an existing file.
- A new `web_drop_dir` config key (default `~/Pictures/Klop`), editable via `klop config set`.

## Non-Goals

- No form field for `web_drop_dir` in the plasmoid settings in v1 (TOML / `config set` only).
- No support for dragged HTML fragments or embedded base64 image data — only a fetchable
  `http(s)` image URL. (`text/html` / `data:` URIs are out of scope.)
- No authenticated / cookie-bound downloads (no browser session reuse); a URL that requires
  login will fail with a clear error.
- No new Python package dependency (uses stdlib `urllib`). The clipboard tool (`wl-copy` /
  `xclip`) is an optional, detected external CLI — absence degrades to "saved, not copied".
- No change to how local-file drops behave.
- No SSRF protection on the fetched host: a user-dragged URL pointing at a local/metadata address
  (e.g. `http://localhost`, `http://169.254.169.254`) is fetched verbatim. Accepted risk — the
  fetch is user-initiated on a desktop app, http/https-only, size-capped, and image-validated.
  (Redirects to non-http(s) schemes are rejected.)

## Architecture

```
Browser image drag ─▶ Klop DropArea.onDropped
   scheme file://  ─▶ klop optimize <path>        (unchanged, Sub-project C)
   scheme http(s)  ─▶ klop optimize-url <url>     (NEW)
                          │  urllib download → temp
                          │  validate image (magic bytes)
                          │  save (dedup) → web_drop_dir
                          │  Engine.optimize in place (+ backup → undoable)
                          │  wl-copy / xclip  ← optimized bytes
                          │  HistoryStore.record("file", …)
                          ▼  desktop notification (non-tty)
```

The CLI is the single place the work happens; the plasmoid only classifies the drop and shells
out, consistent with Sub-project C.

## Components

### New module `webfetch.py` (Qt-free) — download + save + clipboard

Isolates the non-engine concerns so `cli.py` stays thin and everything is unit-testable.

- `download_image(url, *, dest_dir, fetcher=urllib_fetch, max_bytes=50*1024*1024, timeout=15) -> Path`
  - Rejects a non-`http`/`https` scheme with `ValueError`.
  - `fetcher(url, timeout)` returns `(content_bytes, final_url)` (injectable for tests; the
    default uses `urllib.request` with `User-Agent: klop` and the timeout). Reads at most
    `max_bytes`; exceeding it raises `ValueError` ("image too large").
  - Validates the bytes are a real image via `media._detect_by_magic(header_bytes)` (the existing
    byte-oriented magic-bytes helper in [media.py](../../../src/klop/media.py)) on the first
    32 bytes — a non-image (e.g. an HTML error page) yields no/`UNKNOWN` type and raises
    `ValueError`.
  - Computes the filename: basename of the URL path (query stripped); if it has no
    image-type extension, append the extension for the detected `MediaType`
    (`.png/.jpg/.gif/.webp`); sanitize to a safe basename. Dedup against `dest_dir`
    (`name.jpg` → `name-1.jpg` → `name-2.jpg` …). Creates `dest_dir` (expanduser) if missing.
  - Writes the bytes to the deduped path and returns it.

- `copy_image_to_clipboard(path) -> bool`
  - Detects `wl-copy` (Wayland) or `xclip` (X11) via `shutil.which`; runs it with the file's
    MIME type (`wl-copy --type <mime>` reading the file on stdin; `xclip -selection clipboard
    -t <mime> -i <path>`). Returns `True` if a tool ran successfully, `False` if none is present
    or it failed (never raises). MIME derived from the file's `MediaType`.

### `config.py` — new string field

- Add `web_drop_dir: str = "~/Pictures/Klop"` to `Config`.
- Teach the serializer/coercion a **string** type (currently only bool/int/tuple):
  - `_toml_value`: a `str` → a double-quoted, escaped TOML string.
  - `_coerce_like`: when the current value is a `str`, use the raw override verbatim.
  - `config_to_dict` already returns the str as-is; `load_config` already passes str through.
  - `save_config` round-trips it. (Existing tests still pass; add coverage for the str path.)

### `cli.py` — `optimize-url` command

- `_cmd_optimize_url(args)`:
  1. `path = webfetch.download_image(args.url, dest_dir=Path(load_config().web_drop_dir).expanduser())`
     — on `ValueError`, print `error: <msg>` to stderr, exit 1.
  2. `result = engine.optimize(OptimizationJob(source_path=path))` (same engine as `optimize`).
  3. On `OPTIMIZED`: record a `"file"` history row (path, sizes, `backup_id`); print the summary
     line. On `UNCHANGED`/`SKIPPED`: keep the saved file, print status. (`ERROR` → stderr, exit 1.)
  4. `copied = webfetch.copy_image_to_clipboard(path)`.
  5. If not a tty, post the notification (reuse the same summary path as `optimize`): e.g.
     `"foo.jpg — 1.2MB → 0.4MB (-67%)"`, with a body note "Saved to <dir>" and "· copied"
     when `copied`.
  6. Print the saved path so the plasmoid could surface it. Exit 0.
- Register subparser `optimize-url` with one positional `url`.

### Plasmoid `main.qml` — classify drops

- In `onDropped`, split the dropped URLs by scheme: collect local paths (`file://`, as today)
  **and** remote URLs (`http://`/`https://`). When `drop.urls` is empty but `drop.hasText` and
  the text is an `http(s)` URL (some browsers only set `text/plain` / `text/x-moz-url`; take the
  first line), treat that as a remote URL.
- `if (localPaths.length) root.optimizePaths(localPaths)` (unchanged).
- `if (remoteUrls.length) root.optimizeUrls(remoteUrls)` — new function: for each URL,
  `exec.run(shquote(Backend.KLOP_BIN) + " optimize-url " + shquote(url), cb)`; `cb` calls
  `refreshHistory()` (the saved+optimized file shows up as a history row).

## Error handling

- **Bad scheme / non-image / oversize / network error:** `download_image` raises `ValueError`
  (network/urllib errors are caught and re-raised as `ValueError` with a readable message); the
  CLI prints `error: …` to stderr and exits 1. Non-tty runs also post a failure notification
  ("Could not fetch image") so a browser drag that fails is not silent.
- **No clipboard tool:** `copy_image_to_clipboard` returns `False`; the file is still saved and
  in history; the notification omits "· copied". Not an error.
- **Filename collisions:** dedup suffix guarantees no overwrite.
- **`web_drop_dir` missing:** created with `mkdir(parents=True, exist_ok=True)` (after
  `expanduser`).
- **Size cap:** the fetcher stops after `max_bytes` and raises, so a hostile/huge URL can't
  exhaust memory/disk.

## Testing strategy

Headless, Qt-free (no live network; inject a fake `fetcher`).

- **webfetch.py:**
  - non-http scheme → `ValueError`; `data:`/`ftp:` rejected.
  - fake fetcher returning PNG bytes → saves a file in a tmp `dest_dir`, returns its path,
    bytes match.
  - non-image bytes (e.g. `b"<html>…"`) → `ValueError`, nothing written.
  - oversize (fetcher returns > `max_bytes`, or a capped reader) → `ValueError`.
  - filename: URL with query string → basename without query; URL with no extension + PNG
    magic → `.png` appended; existing `name.jpg` in dest → `name-1.jpg`; sanitization of a
    nasty basename.
  - `copy_image_to_clipboard`: `shutil.which` monkeypatched to a fake `wl-copy`; asserts the
    subprocess argv + MIME; returns `False` when neither tool present (no raise).
- **config.py:** `web_drop_dir` round-trips through `save_config`/`load_config`; `apply_overrides`
  coerces a string value; `config_to_dict` includes it; the TOML string is quoted/escaped.
- **cli.py:** `optimize-url` with a fake fetcher + a fake/real engine on a shrinkable fixture →
  writes the file under a tmp `web_drop_dir`, records one `"file"` history row, prints the saved
  path, exits 0; bad scheme → exit 1 + stderr. Clipboard shell-out monkeypatched. CLI stays
  Qt-free (`assert "PySide6" not in sys.modules` in a subprocess, as added in Sub-project C).
- **Manual smoke (real session):** drag an image from a browser onto the Klop icon → a file
  appears in `~/Pictures/Klop`, a notification shows the savings + "copied", the clipboard holds
  the optimized image (paste to confirm), and the popup history shows the new row (undoable).

## Dependencies

- Python: stdlib only (`urllib`, `pathlib`, `shutil`, `subprocess`, `tempfile`). No new package.
- Runtime (optional, detected): `wl-clipboard` (`wl-copy`) on Wayland or `xclip` on X11 for the
  clipboard copy. Absence degrades gracefully to "saved, not copied".

## Build order (for the implementation plan)

1. **`config.py` string-field support** — `web_drop_dir` + serializer/coercion for `str`, TDD.
2. **`webfetch.py`** — `download_image` (scheme/size/image/dedup) + `copy_image_to_clipboard`, TDD
   with an injected fetcher and monkeypatched clipboard tool.
3. **`cli.py` `optimize-url`** — wire download → engine → history → clipboard → notify, TDD.
4. **Plasmoid `main.qml`** — classify drops, add `optimizeUrls`; update the package test.
5. **Manual smoke** on the real session.
