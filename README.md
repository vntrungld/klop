# Klop

A [Clop](https://lowtechguys.com/clop/)-style media optimizer for KDE Plasma 6.
Drop images, videos, or PDFs on the panel widget, right-click them in Dolphin,
or just copy an image. Klop shrinks them with the best tool it finds on your
system, and keeps a backup so you can undo.

## Features

- **Panel widget (plasmoid).** A drop target in the Plasma panel.
  - Drop local files to optimize them in place.
  - Drag an image straight from the browser. Klop downloads it to
    `~/Pictures/Klop`, optimizes it, and copies it to the clipboard. Linked
    images, like Facebook feed photos, work too.
  - The popup lists recent results with open, copy, open-folder, and undo buttons.
- **Result notifications with actions.** After a web drop, the notification has
  **Copy** and **Open folder** buttons.
- **Clipboard auto-optimize.** The tray daemon optimizes images as you copy them
  and puts the smaller version back on the clipboard.
- **Dolphin integration.** An "Optimize with Klop" entry in the right-click menu
  for PNG, JPEG, GIF, and WebP images and MP4, MOV, MKV, and WebM videos.
- **Live progress.** While `klop optimize` runs, a Plasma progress card shows the
  current file and how many are done, then turns into the result summary. The
  panel widget shows the percentage too, and a terminal run draws a bar. Videos
  report a real percentage as ffmpeg encodes.
- **Undo and history.** Originals are backed up before they are replaced (7 days
  / 500 MB by default). Any result can be restored.
- **Safe by default.** A file is only replaced when the result is actually smaller.

## Supported formats

| Format            | Tool                                       |
| ----------------- | ------------------------------------------ |
| PNG               | `pngquant` (lossy, quality 65–80)          |
| JPEG              | `jpegoptim` (max quality 80)               |
| GIF               | `gifsicle`                                 |
| WebP              | `cwebp`, falling back to `vips`            |
| PDF               | `gs` (Ghostscript, `ebook` preset)         |
| MP4 / MOV / MKV / WebM | `ffmpeg` → H.264 MP4 (CRF 28)         |

HEIC is not optimized on purpose, because it is already an efficient codec.
Missing tools are detected at runtime, and those formats are skipped. Run
`klop caps` to see what was found.

## Requirements

- KDE Plasma 6
- Python ≥ 3.11 (PySide6 is installed automatically)
- Optimizer tools for the formats you care about. On Arch, for example:

  ```sh
  sudo pacman -S pngquant jpegoptim gifsicle libwebp libvips ghostscript ffmpeg
  ```

- To copy images to the clipboard: `wl-clipboard` (Wayland) or `xclip` (X11)
- For notification buttons: `notify-send` (libnotify)

## Install

```sh
git clone git@github.com:vntrungld/klop.git
cd klop
python -m venv .venv
.venv/bin/pip install -e .

.venv/bin/klop install   # panel widget + Dolphin menu + daemon service
```

`klop install` sets up all three parts. Pass `--plasmoid`, `--dolphin` or
`--service` to install only those. The widget is added to your first panel
(pass `--no-panel` to skip that and add it yourself via right-click the
panel → *Add Widgets…*). After upgrading, restart plasmashell to load the new
widget code:

```sh
kquitapp6 plasmashell && kstart plasmashell
```

The daemon handles clipboard auto-optimize. `--service` installs it as a
systemd user service (`klop-daemon.service`) that starts with the Plasma
session and runs without a tray icon: the widget shows the savings total,
and its clipboard button turns auto-optimize on and off (the daemon picks
up config changes live).

```sh
systemctl --user status klop-daemon
journalctl --user -u klop-daemon
```

## CLI

```sh
klop optimize FILE...        # optimize files in place (with backup)
klop optimize-url URL...     # download, optimize, save, copy an image
klop copy FILE               # copy an image to the clipboard
klop history [--json]        # show optimization history
klop undo BACKUP_ID          # restore an original
klop caps                    # show detected optimizer tools
klop config get [--json]     # print settings
klop config set key=value... # change settings
```

## Configuration

Settings live in `~/.config/klop/config.toml`. You can edit them from the
widget's settings page or with `klop config set`:

| Key                     | Default           | Meaning                                    |
| ----------------------- | ----------------- | ------------------------------------------ |
| `png_lossy`             | `true`            | Use lossy `pngquant` for PNG               |
| `pngquant_quality`      | `[65, 80]`        | pngquant min/max quality                   |
| `jpeg_max_quality`      | `80`              | JPEG quality cap                           |
| `webp_quality`          | `80`              | WebP quality                               |
| `gif_lossy`             | `0`               | gifsicle lossiness (0 = lossless)          |
| `pdf_setting`           | `ebook`           | `screen` / `ebook` / `printer` / `prepress` |
| `video_crf`             | `28`              | ffmpeg CRF                                 |
| `video_codec`           | `libx264`         | ffmpeg video codec                         |
| `video_preset`          | `medium`          | ffmpeg preset                              |
| `video_threads`         | `0`               | ffmpeg encoder threads per video (0 = all cores) |
| `min_bytes_saved`       | `1`               | Keep the original unless at least this much is saved |
| `concurrency`           | `2`               | Parallel jobs                              |
| `backup_retention_days` | `7`               | How long backups are kept                  |
| `backup_max_bytes`      | `524288000`       | Backup store size cap                      |
| `clipboard_watch`       | `true`            | Auto-optimize copied images (daemon)       |
| `web_drop_dir`          | `~/Pictures/Klop` | Where web drops are saved                  |

History is stored in `~/.local/share/klop/history.jsonl` and backups in
`~/.local/share/klop/backups`.

## Development

```sh
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check src tests
```

Design notes and implementation plans are in `docs/superpowers/`.
