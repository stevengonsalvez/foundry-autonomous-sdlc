"""Tests for the pure-python PNG pixel differ (scripts/ui/png_diff.py)."""

from __future__ import annotations

import struct
import zlib

import pytest

from scripts.ui.png_diff import (
    MIN_CHANGED_PIXELS,
    PngDecodeError,
    decode_png,
    diff_pngs,
    format_pct,
)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _filter_row(kind: int, row: bytes, prev: bytes, bpp: int) -> bytes:
    out = bytearray()
    for i, x in enumerate(row):
        a = row[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        if kind == 0:
            pred = 0
        elif kind == 1:
            pred = a
        elif kind == 2:
            pred = b
        elif kind == 3:
            pred = (a + b) // 2
        else:
            pred = _paeth(a, b, c)
        out.append((x - pred) & 0xFF)
    return bytes([kind]) + bytes(out)


def make_png(
    pixels: list[list[tuple[int, ...]]],
    *,
    color_type: int = 2,
    filters: tuple[int, ...] = (0, 1, 2, 3, 4),
    interlace: int = 0,
    bit_depth: int = 8,
) -> bytes:
    height, width = len(pixels), len(pixels[0])
    bpp = 3 if color_type == 2 else 4
    rows = [bytes(v for px in row for v in px) for row in pixels]
    prev = bytes(width * bpp)
    raw = b""
    for y, row in enumerate(rows):
        raw += _filter_row(filters[y % len(filters)], row, prev, bpp)
        prev = row

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def grid(width: int, height: int, rgb: tuple[int, int, int] = (10, 20, 30)):
    return [[rgb for _ in range(width)] for _ in range(height)]


@pytest.mark.parametrize("kind", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("color_type", [2, 6])
def test_decode_round_trips_every_filter_type(kind: int, color_type: int) -> None:
    pixels = [
        [
            ((x * 7 + y * 3) % 256, (x * 13) % 256, (y * 29) % 256)
            + ((200,) if color_type == 6 else ())
            for x in range(9)
        ]
        for y in range(6)
    ]
    png = make_png(pixels, color_type=color_type, filters=(kind,))
    img = decode_png(png)
    assert (img.width, img.height) == (9, 6)
    assert img.channels == (3 if color_type == 2 else 4)
    expected = [bytes(v for px in row for v in px) for row in pixels]
    assert img.rows == expected


def test_identical_images_have_zero_diff() -> None:
    png = make_png(grid(20, 10))
    d = diff_pngs(png, png)
    assert d.comparable and d.changed_pixels == 0 and d.pct == 0.0 and not d.changed


def test_counts_changed_pixels_and_percentage() -> None:
    a = grid(20, 10)
    b = grid(20, 10)
    for x in range(10):  # 10 changed pixels of 200
        b[3][x] = (255, 0, 0)
    d = diff_pngs(make_png(a), make_png(b))
    assert d.changed_pixels == 10
    assert d.total_pixels == 200
    assert d.pct == pytest.approx(5.0)
    assert d.changed


def test_ignores_sub_tolerance_antialiasing_noise() -> None:
    a = grid(20, 10, (100, 100, 100))
    b = grid(20, 10, (104, 98, 103))  # every pixel off by <= 4 per channel
    d = diff_pngs(make_png(a), make_png(b))
    assert d.changed_pixels == 0 and not d.changed


def test_tiny_change_below_noise_floor_is_not_flagged() -> None:
    a = grid(40, 40)
    b = grid(40, 40)
    for i in range(MIN_CHANGED_PIXELS - 1):
        b[0][i] = (255, 255, 255)
    d = diff_pngs(make_png(a), make_png(b))
    assert d.changed_pixels == MIN_CHANGED_PIXELS - 1
    assert not d.changed


def test_rgb_and_rgba_compare_on_color_channels() -> None:
    rgb = make_png(grid(8, 8, (1, 2, 3)), color_type=2)
    rgba = make_png([[(1, 2, 3, 255)] * 8 for _ in range(8)], color_type=6)
    assert diff_pngs(rgb, rgba).changed_pixels == 0


def test_different_dimensions_are_not_comparable() -> None:
    d = diff_pngs(make_png(grid(8, 8)), make_png(grid(9, 8)))
    assert not d.comparable
    assert d.changed  # unknown must not read as "unchanged"
    assert d.pct is None


@pytest.mark.parametrize(
    "kwargs",
    [{"interlace": 1}, {"bit_depth": 16}],
)
def test_unsupported_formats_raise(kwargs: dict[str, int]) -> None:
    png = make_png(grid(4, 4), **kwargs)
    with pytest.raises(PngDecodeError):
        decode_png(png)


def test_decompression_bomb_is_rejected() -> None:
    png = make_png(grid(4, 4))
    # Rewrite IDAT with far more data than the 4x4 header allows.
    bomb = zlib.compress(b"\x00" * 5_000_000)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = png[16:29]
    evil = (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", bomb) + chunk(b"IEND", b"")
    )
    with pytest.raises(PngDecodeError):
        decode_png(evil)


def test_truncated_data_raises() -> None:
    png = make_png(grid(4, 4))
    with pytest.raises(PngDecodeError):
        decode_png(png[:30])


def test_oversized_dimensions_raise() -> None:
    png = bytearray(make_png(grid(4, 4)))
    png[16:20] = struct.pack(">I", 20000)
    png[20:24] = struct.pack(">I", 20000)
    with pytest.raises(PngDecodeError):
        decode_png(bytes(png))


@pytest.mark.parametrize(
    ("pct", "text"),
    [(0.0, "0%"), (0.004, "<0.01%"), (0.5, "0.50%"), (12.345, "12.35%"), (100.0, "100.00%"), (None, "changed")],
)
def test_format_pct(pct: float | None, text: str) -> None:
    assert format_pct(pct) == text
