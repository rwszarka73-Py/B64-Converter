"""MIME detection, extension mapping, and Base64 input cleanup.
Mirrors MimeHelper.vb from the Windows version."""

import math
import re

MIME_TO_EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
    "image/svg+xml": "svg", "image/bmp": "bmp", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico",
    "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
    "audio/ogg": "ogg", "audio/flac": "flac", "audio/x-flac": "flac", "audio/mp4": "m4a", "audio/x-m4a": "m4a",
    "audio/webm": "weba", "audio/aac": "aac",
    "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov", "video/ogg": "ogv",
    "application/pdf": "pdf", "application/zip": "zip", "text/plain": "txt",
    "application/json": "json", "application/octet-stream": "bin",
}

EXT_TO_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "jfif": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml", "bmp": "image/bmp",
    "ico": "image/x-icon",
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "oga": "audio/ogg",
    "flac": "audio/flac", "m4a": "audio/mp4", "aac": "audio/aac", "weba": "audio/webm",
    "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
    "ogv": "video/ogg",
    "pdf": "application/pdf", "zip": "application/zip", "txt": "text/plain",
    "json": "application/json", "csv": "text/csv", "html": "text/html", "htm": "text/html",
}

_DATA_URI = re.compile(
    r"""data:([^;,"'\s)]*)?((?:;[^;,"'\s)]+)*?);base64,([A-Za-z0-9+/=_\-\s]+)""",
    re.IGNORECASE)
_B64_CHARS = re.compile(r"^[A-Za-z0-9+/]*$")


def extension_for(mime: str) -> str:
    """File extension (no dot) for a MIME type."""
    ext = MIME_TO_EXT.get(mime.lower())
    if ext:
        return ext
    if "/" in mime:
        sub = "".join(c for c in mime.split("/", 1)[1] if c.isalnum())
        if sub:
            return sub
    return "bin"


def mime_for_extension(ext: str) -> str:
    """MIME type for a file extension ('' if unknown). Accepts '.png' or 'png'."""
    return EXT_TO_MIME.get(ext.lstrip(".").lower(), "") if ext else ""


def sniff(b: bytes) -> str:
    """Detect file type from its leading bytes. Returns '' if unrecognized."""
    if not b or len(b) < 4:
        return ""

    def ascii_at(i, n):
        return b[i:i + n].decode("latin-1") if len(b) >= i + n else ""

    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if ascii_at(0, 4) == "GIF8":
        return "image/gif"
    if ascii_at(0, 4) == "RIFF" and ascii_at(8, 4) == "WEBP":
        return "image/webp"
    if ascii_at(0, 4) == "RIFF" and ascii_at(8, 4) == "WAVE":
        return "audio/wav"
    if ascii_at(0, 2) == "BM":
        return "image/bmp"
    if b[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon"
    if ascii_at(0, 3) == "ID3":
        return "audio/mpeg"
    if b[0] == 0xFF and (b[1] & 0xE0) == 0xE0 and (b[1] & 0x06) != 0:
        return "audio/mpeg"          # MPEG frame sync
    if b[0] == 0xFF and (b[1] & 0xF6) == 0xF0:
        return "audio/aac"           # ADTS
    if ascii_at(0, 4) == "OggS":
        return "audio/ogg"
    if ascii_at(0, 4) == "fLaC":
        return "audio/flac"
    if ascii_at(4, 4) == "ftyp":
        brand = ascii_at(8, 4)
        if brand.startswith(("M4A", "M4B")):
            return "audio/mp4"
        if brand == "qt  ":
            return "video/quicktime"
        return "video/mp4"
    if b[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    if ascii_at(0, 4) == "%PDF":
        return "application/pdf"
    if b[:4] == b"PK\x03\x04":
        return "application/zip"

    head = b[:256].decode("utf-8", errors="ignore").lstrip().lstrip("﻿").lstrip().lower()
    if head.startswith("<svg") or (head.startswith("<?xml") and "<svg" in head):
        return "image/svg+xml"
    return ""


def parse_input(text: str):
    """Return (mime, base64_payload) from a data URI, an HTML/CSS snippet, or raw Base64."""
    text = text.strip()
    m = _DATA_URI.search(text)
    if m:
        return (m.group(1) or "").lower(), m.group(3)
    return "", text


def clean_base64(b64: str):
    """Strip whitespace, convert URL-safe chars, repair padding. None if it can't be valid Base64."""
    s = "".join(b64.split()).replace("-", "+").replace("_", "/").rstrip("=")
    if not _B64_CHARS.match(s):
        return None
    if len(s) % 4 == 1:
        return None
    return s + "=" * ((4 - len(s) % 4) % 4)


def format_bytes(n: int) -> str:
    if n == 0:
        return "0 Bytes"
    sizes = ["Bytes", "KB", "MB", "GB"]
    i = min(int(math.floor(math.log(n) / math.log(1024))), len(sizes) - 1)
    return f"{round(n / 1024 ** i, 2):g} {sizes[i]}"
