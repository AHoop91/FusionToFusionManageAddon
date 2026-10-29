"""Makes the white background of a thumbnail transparent.

The Data Model returns some component thumbnails on an opaque white background. Fusion Manage shows an image as it is, so the white
sits as a box on its grey page. Only white that is joined to the edge of the picture is cleared, so white inside the part stays.

Only the standard library is available, so the PNG is read and written here. Just the common case is handled (8-bit RGBA, not
interlaced); any other image is passed on unchanged, and so is one that is damaged or too big to be a thumbnail (a small file can
hold an image that expands to gigabytes, so how much is read out of it is limited).

Pure Python is slow per pixel, so the work is done on whole rows and runs where it can be: a row is undone a channel at a time, with
whole-integer or built-in arithmetic where a filter allows it, and the white is found as runs of pixels in a row, not one pixel at a time.
"""

import re
import struct
import zlib
from bisect import bisect_right
from itertools import accumulate
from typing import Iterator, List, Optional, Tuple

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
RGBA = 4                # bytes per pixel
COLOUR_TYPE_RGBA = 6
WHITE_FROM = 250        # a channel at or above this counts as white, which also takes the faint fringe of an anti-aliased edge
OPAQUE, CLEAR = 255, 0
IHDR_BYTES = 13         # the header chunk: width, height, bit depth, colour type, compression, filter, interlace
MAX_PIXELS = 16_000_000   # more than a thumbnail is: it is not read (a 4000 x 4000 picture is 64 MB of pixels)
FILTER_NONE, FILTER_SUB, FILTER_UP, FILTER_AVERAGE, FILTER_PAETH = range(5)   # the ways a row is stored, by what it is predicted from

Pixels = bytearray      # width * height * RGBA bytes, row after row
Image = Tuple[int, int, Pixels]
Runs = List[List[Tuple[int, int]]]   # for each row, ``(start, end)`` of each run of pixels, ``end`` being the pixel after the last

_WHITE_CHANNEL = bytes(1 if value >= WHITE_FROM else 0 for value in range(256))   # a channel value -> 1 when it is white
_WHITE_RUN = re.compile(b"\x01+")
_LOW_BYTE = (255).__and__


def clear_white_background(data: bytes) -> bytes:
    """``data`` with its edge-connected white made transparent; unchanged if it is not a PNG this module reads, already has
    transparency, or has no white edge."""
    image = read_png(data)
    if image is None:
        return data
    width, height, pixels = image
    alpha = pixels[RGBA - 1::RGBA]
    if alpha.count(OPAQUE) != len(alpha):   # some of it is transparent already
        return data
    if not _clear_edge_white(width, height, pixels):
        return data
    return write_png(width, height, pixels)


def read_png(data: bytes) -> Optional[Image]:
    """``(width, height, pixels)`` of an 8-bit, non-interlaced RGBA PNG, or None for anything else (damaged data, or an image of more than
    ``MAX_PIXELS``)."""
    if not data.startswith(PNG_SIGNATURE):
        return None
    header, compressed = None, []
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            if len(body) != IHDR_BYTES:
                return None
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed.append(body)
    if header is None or not compressed:
        return None
    width, height, depth, colour, _, _, interlace = header
    if (depth, colour, interlace) != (8, COLOUR_TYPE_RGBA, 0) or not width or not height or width * height > MAX_PIXELS:
        return None
    expected = height * (width * RGBA + 1)   # every row has its filter byte
    try:
        raw = zlib.decompressobj().decompress(b"".join(compressed), expected + 1)   # one byte more than it should hold shows it holds more
    except zlib.error:
        return None
    pixels = _unfilter(raw, width, height) if len(raw) == expected else None
    return (width, height, pixels) if pixels is not None else None


def write_png(width: int, height: int, pixels: Pixels) -> bytes:
    """An 8-bit RGBA PNG of ``pixels`` (rows are stored unfiltered; the compression does the work)."""
    stride = width * RGBA
    rows = b"".join(b"\x00" + bytes(pixels[start:start + stride]) for start in range(0, len(pixels), stride))
    header = struct.pack(">IIBBBBB", width, height, 8, COLOUR_TYPE_RGBA, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows)) + _chunk(b"IEND", b"")


def _chunks(data: bytes) -> Iterator[Tuple[bytes, bytes]]:
    """The ``(type, body)`` of each chunk of a PNG, in order; a chunk cut short by the end of the data has the body there is."""
    position = len(PNG_SIGNATURE)
    while position + 8 <= len(data):
        size, kind = struct.unpack(">I4s", data[position:position + 8])
        yield kind, data[position + 8:position + 8 + size]
        position += 12 + size   # length, type, body and the checksum


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def _unfilter(raw: bytes, width: int, height: int) -> Optional[Pixels]:
    """The pixels of the decompressed image data, whose every row starts with the byte of the filter that was applied to it."""
    stride = width * RGBA
    if len(raw) < height * (stride + 1):
        return None
    pixels = Pixels(height * stride)
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        row = bytearray(raw[start + 1:start + 1 + stride])
        if not _undo_filter(raw[start], row, previous):
            return None
        pixels[y * stride:(y + 1) * stride] = row
        previous = row
    return pixels


def _undo_filter(kind: int, row: bytearray, previous: bytearray) -> bool:
    """Turn ``row`` from its filtered bytes into pixel bytes, given the finished row above it; False for an unknown filter.

    A byte is predicted from the byte of the same channel on its left and above, never from another channel, so the four channels are
    undone one at a time (each a row of ``width`` bytes)."""
    if kind == FILTER_NONE:
        return True
    if kind == FILTER_UP:
        row[:] = _add_bytes(row, previous)
        return True
    if kind not in (FILTER_SUB, FILTER_AVERAGE, FILTER_PAETH):
        return False
    for channel in range(RGBA):
        row[channel::RGBA] = _undo_channel(kind, row[channel::RGBA], previous[channel::RGBA])
    return True


def _add_bytes(first: bytes, second: bytes) -> bytes:
    """The two byte strings added byte by byte, each sum modulo 256, in the time of a few whole-integer operations: the low seven bits of
    every byte are added where a carry cannot pass into the next byte, and the top bit is then put back as the sum of the top bits."""
    size = len(first)
    low, high = int.from_bytes(b"\x7f" * size, "big"), int.from_bytes(b"\x80" * size, "big")
    x, y = int.from_bytes(first, "big"), int.from_bytes(second, "big")
    return (((x & low) + (y & low)) ^ ((x ^ y) & high)).to_bytes(size, "big")


def _undo_channel(kind: int, filtered: bytes, above: bytes) -> bytes:
    """One channel of a row, undone: ``filtered`` is its stored bytes and ``above`` the same channel of the row above, both ``width`` long."""
    if kind == FILTER_SUB:   # every byte is the sum of those before it
        return bytes(map(_LOW_BYTE, accumulate(filtered)))
    out = bytearray(len(filtered))
    left = 0
    if kind == FILTER_AVERAGE:
        for x, (stored, up) in enumerate(zip(filtered, above)):
            left = out[x] = (stored + ((left + up) >> 1)) & 255
        return bytes(out)
    corner = 0   # Paeth: the one of left, up and the corner (above left) that is nearest to left + up - corner
    for x, (stored, up) in enumerate(zip(filtered, above)):
        from_left, from_up, from_both = abs(up - corner), abs(left - corner), abs(left + up - 2 * corner)
        if from_left <= from_up and from_left <= from_both:
            predicted = left
        elif from_up <= from_both:
            predicted = up
        else:
            predicted = corner
        left = out[x] = (stored + predicted) & 255
        corner = up
    return bytes(out)


def _white_runs(width: int, height: int, pixels: Pixels) -> Runs:
    """For each row, the runs of white pixels in it. A pixel is white when all three colour channels are, found for the whole picture at once."""
    white = [int.from_bytes(pixels[channel::RGBA].translate(_WHITE_CHANNEL), "big") for channel in range(RGBA - 1)]
    mask = (white[0] & white[1] & white[2]).to_bytes(width * height, "big")   # a byte a pixel: 1 where it is white
    return [[(run.start() - y * width, run.end() - y * width) for run in _WHITE_RUN.finditer(mask, y * width, (y + 1) * width)]
            for y in range(height)]   # (the matches are placed in the whole mask: where in the row is what is wanted)


def _clear_edge_white(width: int, height: int, pixels: Pixels) -> int:
    """Make every white pixel reachable from the edge through white pixels transparent; returns how many were cleared.

    Works on the runs of white in each row: a run is reached from a run above or below it that it overlaps, so it is the runs that are
    walked, not the pixels (a picture has a few hundred runs, and hundreds of thousands of pixels)."""
    runs = _white_runs(width, height, pixels)
    starts = [[start for start, _ in row] for row in runs]
    reached = [[False] * len(row) for row in runs]
    stack = [(y, i) for y, row in enumerate(runs) for i, (start, end) in enumerate(row)
             if y in (0, height - 1) or start == 0 or end == width]   # the runs that touch the edge
    cleared = 0
    while stack:
        y, i = stack.pop()
        if reached[y][i]:
            continue
        reached[y][i] = True
        start, end = runs[y][i]
        cleared += end - start
        first = (y * width + start) * RGBA + RGBA - 1
        pixels[first:(y * width + end) * RGBA:RGBA] = bytes([CLEAR]) * (end - start)   # their alpha bytes, at once
        for beside in (y - 1, y + 1):
            if 0 <= beside < height:
                for j in _overlapping(runs[beside], starts[beside], start, end):
                    if not reached[beside][j]:
                        stack.append((beside, j))
    return cleared


def _overlapping(row: List[Tuple[int, int]], starts: List[int], start: int, end: int) -> Iterator[int]:
    """The places in ``row`` (runs, in order, with their ``starts``) of the runs that overlap ``start`` to ``end``."""
    for j in range(max(bisect_right(starts, start) - 1, 0), len(row)):   # from the run at or before ``start``, which may reach over it
        other_start, other_end = row[j]
        if other_start >= end:
            return
        if other_end > start:
            yield j
