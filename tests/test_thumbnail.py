"""Making the white background of a thumbnail transparent."""

import struct
import unittest
import zlib

from src.publish.thumbnail import PNG_SIGNATURE, clear_white_background, read_png, write_png

W, D, CLEAR = (255, 255, 255, 255), (40, 40, 40, 255), (255, 255, 255, 0)


def png(rows):
    """An RGBA PNG from rows of (r, g, b, a) pixels."""
    pixels = bytearray(c for row in rows for pixel in row for c in pixel)
    return write_png(len(rows[0]), len(rows), pixels)


def alphas(data):
    width, height, pixels = read_png(data)
    return [[pixels[(y * width + x) * 4 + 3] for x in range(width)] for y in range(height)]


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def filtered_png(kind, rows):
    """A PNG whose every row is stored with PNG filter ``kind`` (1 sub, 2 up, 3 average, 4 Paeth)."""
    stride, previous, raw = len(rows[0]) * 4, bytes(len(rows[0]) * 4), b""
    for row in rows:
        line = bytes(c for pixel in row for c in pixel)
        out = bytearray()
        for x, value in enumerate(line):
            left = line[x - 4] if x >= 4 else 0
            up = previous[x]
            corner = previous[x - 4] if x >= 4 else 0
            near = {1: left, 2: up, 3: (left + up) // 2}.get(kind)
            if kind == 4:
                a, b, c = abs(up - corner), abs(left - corner), abs(left + up - 2 * corner)
                near = left if a <= b and a <= c else (up if b <= c else corner)
            out.append((value - near) & 255)
        raw += bytes([kind]) + bytes(out)
        previous = line
    header = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 6, 0, 0, 0)
    return PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class ClearWhiteBackgroundTests(unittest.TestCase):
    def test_white_joined_to_the_edge_is_cleared_and_the_part_stays(self):
        out = clear_white_background(png([[W, W, W, W, W], [W, D, D, D, W], [W, D, W, D, W], [W, D, D, D, W], [W, W, W, W, W]]))
        a = alphas(out)
        self.assertEqual(a[0], [0] * 5)
        self.assertEqual(a[1], [0, 255, 255, 255, 0])
        self.assertEqual(a[2], [0, 255, 255, 255, 0])   # the white inside the ring is shut in, so it stays

    def test_white_reaches_in_through_a_gap_in_the_outline(self):
        out = clear_white_background(png([[W, W, W], [D, W, D], [D, D, D]]))
        self.assertEqual(alphas(out), [[0, 0, 0], [255, 0, 255], [255, 255, 255]])

    def test_an_image_that_already_has_transparency_is_left_alone(self):
        data = png([[CLEAR, W], [W, W]])
        self.assertEqual(clear_white_background(data), data)

    def test_something_that_is_not_a_png_is_left_alone(self):
        self.assertEqual(clear_white_background(b"not a png"), b"not a png")

    def test_a_damaged_png_is_left_alone(self):
        data = png([[W, D], [D, D]])
        damaged = data[:-30] + bytes(30)
        self.assertEqual(clear_white_background(damaged), damaged)

    def test_a_part_with_no_white_edge_is_left_alone(self):
        data = png([[D, D], [D, D]])
        self.assertEqual(clear_white_background(data), data)

    def test_every_png_row_filter_is_read_back_the_same(self):
        rows = [[(10, 20, 30, 255), (200, 100, 50, 255), (7, 8, 9, 255)], [(1, 2, 3, 255), (250, 251, 252, 255), (99, 98, 97, 255)],
                [(0, 0, 0, 255), (255, 255, 255, 255), (128, 64, 32, 255)]]
        expected = bytes(c for row in rows for pixel in row for c in pixel)
        for kind in (1, 2, 3, 4):
            _, _, pixels = read_png(filtered_png(kind, rows))
            self.assertEqual(bytes(pixels), expected, f"filter {kind}")


if __name__ == "__main__":
    unittest.main()
