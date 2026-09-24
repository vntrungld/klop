"""Download a remote image, save it, and copy it to the clipboard.

Qt-free: the plasmoid's web-drop path shells out to `klop optimize-url`,
which uses this module. Downloading is stdlib urllib; the clipboard copy is an
optional, detected external tool (wl-copy / xclip).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from .media import MediaType, _detect_by_magic, detect_media_type
from .paths import dedup

_MAX_DOWNLOAD = 50 * 1024 * 1024  # 50 MB

_TYPE_EXT = {
    MediaType.PNG: ".png",
    MediaType.JPEG: ".jpg",
    MediaType.GIF: ".gif",
    MediaType.WEBP: ".webp",
    MediaType.HEIC: ".heic",
}
_TYPE_MIME = {
    MediaType.PNG: "image/png",
    MediaType.JPEG: "image/jpeg",
    MediaType.GIF: "image/gif",
    MediaType.WEBP: "image/webp",
    MediaType.HEIC: "image/heic",
}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif"}


def _urllib_fetch(
    url: str, timeout: float, cap: int = _MAX_DOWNLOAD
) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "klop"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(cap + 1)  # bound memory
            return data, resp.geturl()
    except Exception as exc:  # URLError, timeout, HTTPError, ...
        raise ValueError(f"could not fetch {url}: {exc}") from exc


def _sanitize(name: str) -> str:
    name = name.replace("/", "_").replace("\\", "_")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name.strip("._") or "image"


def _filename_for(url: str, mtype: MediaType) -> str:
    base = _sanitize(unquote(urlparse(url).path.rsplit("/", 1)[-1]))
    root, ext = os.path.splitext(base)
    if ext.lower() in _IMAGE_EXTS:
        return base
    return (root or "image") + _TYPE_EXT[mtype]


def download_image(
    url: str,
    *,
    dest_dir: Path,
    fetcher=None,
    max_bytes: int = _MAX_DOWNLOAD,
    timeout: float = 15,
) -> Path:
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {scheme or '(none)'}")
    fetch = fetcher or (lambda u, t: _urllib_fetch(u, t, max_bytes))
    content, final_url = fetch(url, timeout)
    if urlparse(final_url or url).scheme.lower() not in ("http", "https"):
        raise ValueError(f"unsupported redirect scheme: {urlparse(final_url).scheme}")
    if len(content) > max_bytes:
        raise ValueError("image too large")
    mtype = _detect_by_magic(content[:32])
    if mtype not in _TYPE_EXT:  # None or a non-image type (video/pdf/unknown)
        raise ValueError("not an image")
    dest_dir = Path(dest_dir).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dedup(dest_dir / _filename_for(final_url or url, mtype))
    target.write_bytes(content)
    return target


def copy_image_to_clipboard(path: Path) -> bool:
    mime = _TYPE_MIME.get(detect_media_type(Path(path)))
    if mime is None:
        return False
    wl = shutil.which("wl-copy")
    if wl:
        try:
            with open(path, "rb") as fh:
                subprocess.run(
                    [wl, "--type", mime],
                    stdin=fh,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=True,
                )
            return True
        except (OSError, subprocess.SubprocessError):
            return False
    xc = shutil.which("xclip")
    if xc:
        try:
            subprocess.run(
                [xc, "-selection", "clipboard", "-t", mime, "-i", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10, check=True,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            return False
    return False
