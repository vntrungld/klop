from __future__ import annotations

import enum
from pathlib import Path


class MediaType(enum.Enum):
    PNG = "png"
    JPEG = "jpeg"
    GIF = "gif"
    WEBP = "webp"
    HEIC = "heic"
    VIDEO = "video"
    PDF = "pdf"
    UNKNOWN = "unknown"


_EXT_MAP = {
    ".png": MediaType.PNG,
    ".jpg": MediaType.JPEG,
    ".jpeg": MediaType.JPEG,
    ".gif": MediaType.GIF,
    ".webp": MediaType.WEBP,
    ".heic": MediaType.HEIC,
    ".heif": MediaType.HEIC,
    ".pdf": MediaType.PDF,
    ".mp4": MediaType.VIDEO,
    ".mov": MediaType.VIDEO,
    ".mkv": MediaType.VIDEO,
    ".webm": MediaType.VIDEO,
}


def _detect_by_magic(header: bytes) -> MediaType | None:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaType.PNG
    if header.startswith(b"\xff\xd8\xff"):
        return MediaType.JPEG
    if header.startswith((b"GIF87a", b"GIF89a")):
        return MediaType.GIF
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return MediaType.WEBP
    if header.startswith(b"%PDF"):
        return MediaType.PDF
    # ISO-BMFF: "....ftyp<brand>"; HEIC brands start with hei/hev/mif.
    if header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand[:3] in (b"hei", b"hev", b"mif"):
            return MediaType.HEIC
        return MediaType.VIDEO
    if header.startswith(b"\x1a\x45\xdf\xa3"):  # Matroska / WebM (EBML)
        return MediaType.VIDEO
    return None


def detect_media_type(path: Path) -> MediaType:
    """Identify media type by magic bytes, falling back to file extension."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(32)
    except OSError:
        header = b""
    by_magic = _detect_by_magic(header)
    if by_magic is not None:
        return by_magic
    return _EXT_MAP.get(path.suffix.lower(), MediaType.UNKNOWN)
