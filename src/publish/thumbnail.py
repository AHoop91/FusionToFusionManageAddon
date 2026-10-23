"""Makes the white background of a thumbnail transparent.

The Data Model returns some component thumbnails on an opaque white background. Fusion Manage shows an image as it is, so the white
sits as a box on its grey page. Only white that is joined to the edge of the picture is cleared, so white inside the part stays.

Only the standard library is available, so the PNG is read and written here. Just the common case is handled (8-bit RGBA, not
interlaced); any other image is passed on unchanged.
"""

import struct
import zlib
from typing import Iterator, List, Optional, Tuple

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
RGBA = 4                # bytes per pixel
COLOUR_TYPE_RGBA = 6
WHITE_FROM = 250        # a channel at or above this counts as white, which also takes the faint fringe of an anti-aliased edge
OPAQUE, CLEAR = 255, 0

Pixels = bytearray      # width * height * RGBA bytes, row after row
Image = Tuple[int, int, Pixels]


def clear_white_background(data: bytes) -> bytes:
    """``data`` with its edge-connected white made transparent; unchanged if it is not a PNG this module reads, already has
    transparency, or has no white edge."""
    image = read_png(data)
    if image is None:
        return data
    width, height, pixels = image
    if any(pixels[alpha] != OPAQUE for alpha in range(RGBA - 1, len(pixels), RGBA)):
        return data
    if not _clear_edge_white(width, height, pixels):
        return data
    return write_png(width, height, pixels)


def read_png(data: bytes) -> Optional[Image]:
    """``(width, height, pixels)`` of an 8-bit, non-interlaced RGBA PNG, or None for anything else (including damaged data)."""
    if not data.startswith(PNG_SIGNATURE):
        return None
    header, compressed = None, []
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed.append(body)
    if header is None or not compressed:
        return None
    width, height, depth, colour, _, _, interlace = header
    if (depth, colour, interlace) != (8, COLOUR_TYPE_RGBA, 0) or not width or not height:
        return None
    try:
        pixels = _unfilter(zlib.decompress(b"".join(compressed)), width, height)
    except zlib.error:
        return None
    return (width, height, pixels) if pixels is not None else None


def write_png(width: int, height: int, pixels: Pixels) -> bytes:
    """An 8-bit RGBA PNG of ``pixels`` (rows are stored unfiltered; the compression does the work)."""
    stride = width * RGBA
    rows = b"".join(b"\x00" + bytes(pixels[start:start + stride]) for start in range(0, len(pixels), stride))
    header = struct.pack(">IIBBBBB", width, height, 8, COLOUR_TYPE_RGBA, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows)) + _chunk(b"IEND", b"")


def _chunks(data: bytes) -> Iterator[Tuple[bytes, bytes]]:
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
    """Turn ``row`` from its filtered bytes into pixel bytes, given the finished row above it; False for an unknown filter."""
    if kind == 0:   # none
        return True
    for x in range(len(row)):
        left = row[x - RGBA] if x >= RGBA else 0
        up = previous[x]
        if kind == 1:        # sub
            predicted = left
        elif kind == 2:      # up
            predicted = up
        elif kind == 3:      # average
            predicted = (left + up) // 2
        elif kind == 4:      # Paeth
            predicted = _paeth(left, up, previous[x - RGBA] if x >= RGBA else 0)
        else:
            return False
        row[x] = (row[x] + predicted) & 255
    return True


def _paeth(left: int, up: int, corner: int) -> int:
    """Whichever of the three neighbours is closest to ``left + up - corner``."""
    from_left, from_up, from_corner = abs(up - corner), abs(left - corner), abs(left + up - 2 * corner)
    if from_left <= from_up and from_left <= from_corner:
        return left
    return up if from_up <= from_corner else corner


def _clear_edge_white(width: int, height: int, pixels: Pixels) -> int:
    """Make every white pixel reachable from the edge through white pixels transparent; returns how many were cleared."""
    def is_white(index: int) -> bool:
        base = index * RGBA
        return min(pixels[base:base + RGBA - 1]) >= WHITE_FROM

    edge: List[int] = list(range(width)) + list(range((height - 1) * width, height * width))
    edge += [y * width for y in range(height)] + [y * width + width - 1 for y in range(height)]
    visited = bytearray(width * height)
    stack = edge
    cleared = 0
    while stack:
        index = stack.pop()
        if visited[index] or not is_white(index):
            continue
        visited[index] = 1
        pixels[index * RGBA + RGBA - 1] = CLEAR
        cleared += 1
        x, y = index % width, index // width
        if x:
            stack.append(index - 1)
        if x < width - 1:
            stack.append(index + 1)
        if y:
            stack.append(index - width)
        if y < height - 1:
            stack.append(index + width)
    return cleared
