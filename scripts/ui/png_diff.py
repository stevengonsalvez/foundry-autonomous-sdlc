"""Pure-python PNG pixel diff for the UI proof (no Pillow, no numpy, no subprocess).

Input PNGs are untrusted workflow artifacts that validate_artifact.py has already
framed and size-checked; this module still bounds everything it does: pixel count,
decompressed size and supported formats (8-bit RGB/RGBA, non-interlaced, which is
what Playwright emits). Anything else raises PngDecodeError and callers fall back
to "changed, amount unknown" rather than guessing.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_PIXELS = 4_000_000

# A pixel counts as changed when any colour channel moves by more than this (of 255):
# sub-pixel text antialiasing differs by a few levels between otherwise identical runs.
CHANNEL_TOLERANCE = 10
# Fewer changed pixels than this is rendering noise, not a UI change.
MIN_CHANGED_PIXELS = 8


class PngDecodeError(ValueError):
    """Raised for PNGs this differ cannot (or will not) decode."""


@dataclass(frozen=True)
class Image:
    width: int
    height: int
    channels: int
    rows: list[bytes]  # unfiltered scanlines, channels bytes per pixel


@dataclass(frozen=True)
class PixelDiff:
    comparable: bool
    changed_pixels: int = 0
    total_pixels: int = 0

    @property
    def pct(self) -> float | None:
        if not self.comparable or self.total_pixels == 0:
            return None
        return 100.0 * self.changed_pixels / self.total_pixels

    @property
    def changed(self) -> bool:
        # Unknown (not comparable) must never read as "unchanged".
        return (not self.comparable) or self.changed_pixels >= MIN_CHANGED_PIXELS


def format_pct(pct: float | None) -> str:
    if pct is None:
        return "changed"
    if pct == 0:
        return "0%"
    if pct < 0.01:
        return "<0.01%"
    return f"{pct:.2f}%"


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(kind: int, row: bytearray, prev: bytes, bpp: int) -> None:
    n = len(row)
    if kind == 0:
        return
    if kind == 1:  # Sub
        for i in range(bpp, n):
            row[i] = (row[i] + row[i - bpp]) & 0xFF
    elif kind == 2:  # Up
        for i in range(n):
            row[i] = (row[i] + prev[i]) & 0xFF
    elif kind == 3:  # Average
        for i in range(n):
            left = row[i - bpp] if i >= bpp else 0
            row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
    elif kind == 4:  # Paeth
        for i in range(n):
            left = row[i - bpp] if i >= bpp else 0
            upleft = prev[i - bpp] if i >= bpp else 0
            row[i] = (row[i] + _paeth(left, prev[i], upleft)) & 0xFF
    else:
        raise PngDecodeError(f"unknown PNG filter type {kind}")


def decode_png(content: bytes) -> Image:
    if len(content) < 33 or not content.startswith(PNG_MAGIC):
        raise PngDecodeError("not a PNG")
    pos = 8
    ihdr: tuple[int, int, int, int, int, int, int] | None = None
    idat = bytearray()
    while pos + 8 <= len(content):
        length, tag = struct.unpack(">I4s", content[pos : pos + 8])
        end = pos + 8 + length
        if end + 4 > len(content):
            raise PngDecodeError("truncated PNG chunk")
        body = content[pos + 8 : end]
        if tag == b"IHDR":
            if length != 13:
                raise PngDecodeError("bad IHDR")
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos = end + 4
    if ihdr is None:
        raise PngDecodeError("missing IHDR")

    width, height, depth, color_type, _comp, _filt, interlace = ihdr
    if depth != 8 or color_type not in (2, 6) or interlace != 0:
        raise PngDecodeError(
            f"unsupported PNG format (depth={depth}, color_type={color_type}, "
            f"interlace={interlace})"
        )
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise PngDecodeError(f"unsupported PNG dimensions {width}x{height}")

    channels = 3 if color_type == 2 else 4
    stride = width * channels
    expected = height * (stride + 1)
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(bytes(idat), expected + 1)
    except zlib.error as exc:
        raise PngDecodeError(f"corrupt PNG data: {exc}") from exc
    if len(raw) != expected or inflater.unconsumed_tail:
        raise PngDecodeError("PNG pixel data size does not match its header")

    rows: list[bytes] = []
    prev = bytes(stride)
    for y in range(height):
        start = y * (stride + 1)
        row = bytearray(raw[start + 1 : start + 1 + stride])
        _unfilter(raw[start], row, prev, channels)
        prev = bytes(row)
        rows.append(prev)
    return Image(width, height, channels, rows)


def _count_changed_in_row(a: bytes, b: bytes, ca: int, cb: int, tolerance: int) -> int:
    changed = 0
    for x in range(len(a) // ca):
        ia, ib = x * ca, x * cb
        if (
            abs(a[ia] - b[ib]) > tolerance
            or abs(a[ia + 1] - b[ib + 1]) > tolerance
            or abs(a[ia + 2] - b[ib + 2]) > tolerance
        ):
            changed += 1
    return changed


def diff_pngs(before: bytes, after: bytes, tolerance: int = CHANNEL_TOLERANCE) -> PixelDiff:
    """Compare two PNGs; raises PngDecodeError if either cannot be decoded."""
    a, b = decode_png(before), decode_png(after)
    if (a.width, a.height) != (b.width, b.height):
        return PixelDiff(comparable=False)
    changed = 0
    for ra, rb in zip(a.rows, b.rows, strict=True):
        # Identical rows are the common case; skip the per-pixel loop for them.
        if a.channels == b.channels and ra == rb:
            continue
        changed += _count_changed_in_row(ra, rb, a.channels, b.channels, tolerance)
    return PixelDiff(comparable=True, changed_pixels=changed, total_pixels=a.width * a.height)
