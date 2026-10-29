"""Making the white background of a thumbnail transparent."""

import struct
import unittest
import zlib
from random import Random

from src.publish.thumbnail import (PNG_SIGNATURE, _add_bytes, _clear_edge_white, clear_white_background, read_png, write_png)

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
    """A PNG whose every row is stored with PNG filter ``kind`` (1 sub, 2 up, 3 average, 4 Paeth), or row by row with each of a list of them."""
    kinds = [kind] * len(rows) if isinstance(kind, int) else list(kind)
    stride, previous, raw = len(rows[0]) * 4, bytes(len(rows[0]) * 4), b""
    for kind, row in zip(kinds, rows):
        line = bytes(c for pixel in row for c in pixel)
        out = bytearray()
        for x, value in enumerate(line):
            left = line[x - 4] if x >= 4 else 0
            up = previous[x]
            corner = previous[x - 4] if x >= 4 else 0
            near = {0: 0, 1: left, 2: up, 3: (left + up) // 2}.get(kind)
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


def png_of(header, idat):
    """A PNG with the given IHDR body and the given (uncompressed) image data."""
    return PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(idat)) + chunk(b"IEND", b"")


class WhatIsReadTests(unittest.TestCase):
    def test_what_is_written_is_read_back_pixel_for_pixel(self):
        rows = [[W, D, (1, 2, 3, 4)], [D, W, (9, 8, 7, 6)]]
        _, _, pixels = read_png(png(rows))
        self.assertEqual(bytes(pixels), bytes(c for row in rows for pixel in row for c in pixel))

    def test_only_8_bit_rgba_that_is_not_interlaced_is_read(self):
        for depth, colour, interlace in ((16, 6, 0), (8, 2, 0), (8, 3, 0), (8, 6, 1)):
            with self.subTest(depth=depth, colour=colour, interlace=interlace):
                header = struct.pack(">IIBBBBB", 2, 2, depth, colour, 0, 0, interlace)
                self.assertIsNone(read_png(png_of(header, bytes(2 * (2 * 4 + 1)))))

    def test_a_header_that_is_cut_short_is_not_read_and_does_not_raise(self):
        data = PNG_SIGNATURE + chunk(b"IHDR", b"\x00\x00\x00\x02") + chunk(b"IDAT", zlib.compress(b"x")) + chunk(b"IEND", b"")
        self.assertIsNone(read_png(data))
        self.assertEqual(clear_white_background(data), data)

    def test_data_cut_off_in_the_middle_of_a_chunk_is_not_read(self):
        data = png([[W, D], [D, D]])
        self.assertIsNone(read_png(data[:40]))
        self.assertIsNone(read_png(PNG_SIGNATURE))

    def test_image_data_with_too_few_or_too_many_rows_is_not_read(self):
        header = struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)
        row = bytes(1 + 2 * 4)
        self.assertIsNone(read_png(png_of(header, row)))   # one row of two
        self.assertIsNone(read_png(png_of(header, row * 3)))   # three rows of two

    def test_a_small_file_that_expands_to_a_huge_image_is_not_expanded(self):
        header = struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)
        bomb = png_of(header, bytes(40_000_000))   # a few kilobytes that hold 40 MB
        self.assertLess(len(bomb), 100_000)
        self.assertIsNone(read_png(bomb))
        self.assertEqual(clear_white_background(bomb), bomb)

    def test_a_picture_of_more_pixels_than_a_thumbnail_is_not_read(self):
        header = struct.pack(">IIBBBBB", 5000, 5000, 8, 6, 0, 0, 0)
        self.assertIsNone(read_png(png_of(header, b"\x00")))

    def test_a_picture_with_no_size_is_not_read(self):
        header = struct.pack(">IIBBBBB", 0, 2, 8, 6, 0, 0, 0)
        self.assertIsNone(read_png(png_of(header, b"")))


def random_rows(random, width, height, white=0.0):
    """Rows of random pixels, opaque; a share ``white`` of them white or nearly (so the white forms regions of every shape)."""
    palette = [(255, 255, 255, 255), (250, 251, 252, 255), (255, 254, 250, 255)]
    return [[random.choice(palette) if random.random() < white else tuple(random.randrange(256) for _ in range(3)) + (255,)
             for _ in range(width)] for _ in range(height)]


def pixel_bytes(rows):
    return bytes(c for row in rows for pixel in row for c in pixel)


def reference_clear_edge_white(width, height, pixels):
    """The way the white was found a pixel at a time: the oracle the runs of white are checked against."""
    def is_white(index):
        return min(pixels[index * 4:index * 4 + 3]) >= 250

    stack = list(range(width)) + list(range((height - 1) * width, height * width))
    stack += [y * width for y in range(height)] + [y * width + width - 1 for y in range(height)]
    visited, cleared = bytearray(width * height), 0
    while stack:
        index = stack.pop()
        if visited[index] or not is_white(index):
            continue
        visited[index] = 1
        pixels[index * 4 + 3] = 0
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


class CheckedAgainstTheSimpleWayTests(unittest.TestCase):
    """What was made fast gives what the simple way gives, on pictures of every shape."""

    SIZES = [(1, 1), (1, 9), (9, 1), (2, 2), (3, 7), (7, 3), (16, 16), (33, 21), (64, 48)]

    def test_every_filter_gives_back_the_pixels_it_was_made_from(self):
        random = Random(11)
        for width, height in self.SIZES:
            rows = random_rows(random, width, height)
            for kind in (0, 1, 2, 3, 4):
                with self.subTest(size=(width, height), filter=kind):
                    self.assertEqual(bytes(read_png(filtered_png(kind, rows))[2]), pixel_bytes(rows))

    def test_rows_with_a_different_filter_each_give_back_the_pixels_they_were_made_from(self):
        random = Random(12)
        for width, height in self.SIZES:
            rows = random_rows(random, width, height)
            kinds = [random.choice((0, 1, 2, 3, 4)) for _ in rows]
            with self.subTest(size=(width, height), kinds=kinds):
                self.assertEqual(bytes(read_png(filtered_png(kinds, rows))[2]), pixel_bytes(rows))

    def test_bytes_are_added_modulo_256_each_on_its_own(self):
        random = Random(13)
        for size in (1, 2, 3, 8, 255, 1024):
            first, second = bytes(random.randrange(256) for _ in range(size)), bytes(random.randrange(256) for _ in range(size))
            with self.subTest(size=size):
                self.assertEqual(_add_bytes(first, second), bytes((a + b) & 255 for a, b in zip(first, second)))
        self.assertEqual(_add_bytes(b"\xff\x80\x00\x7f", b"\x01\x80\x00\x01"), b"\x00\x00\x00\x80")   # the carries stay in their byte

    def test_the_white_cleared_is_the_white_the_simple_way_clears(self):
        random = Random(14)
        for width, height in self.SIZES:
            for white in (0.2, 0.5, 0.7, 0.9, 1.0):
                rows = random_rows(random, width, height, white)
                fast, simple = bytearray(pixel_bytes(rows)), bytearray(pixel_bytes(rows))
                with self.subTest(size=(width, height), white=white):
                    self.assertEqual(_clear_edge_white(width, height, fast), reference_clear_edge_white(width, height, simple))
                    self.assertEqual(fast, simple)

    def test_a_whole_picture_through_both_is_the_same_picture(self):
        random = Random(15)
        rows = random_rows(random, 40, 30, 0.7)
        kinds = [random.choice((1, 2, 3, 4)) for _ in rows]
        simple = bytearray(pixel_bytes(rows))
        reference_clear_edge_white(40, 30, simple)
        _, _, cleared = read_png(clear_white_background(filtered_png(kinds, rows)))
        self.assertEqual(bytes(cleared), bytes(simple))


class WhiteTests(unittest.TestCase):
    def test_a_single_white_pixel_is_cleared(self):
        self.assertEqual(alphas(clear_white_background(png([[W]]))), [[0]])

    def test_a_one_pixel_wide_picture_is_cleared_to_where_the_part_starts(self):
        self.assertEqual(alphas(clear_white_background(png([[W], [W], [D], [W]]))), [[0], [0], [255], [0]])

    def test_what_counts_as_white_is_every_channel_near_the_top(self):
        near, off = (250, 250, 250, 255), (249, 255, 255, 255)
        self.assertEqual(alphas(clear_white_background(png([[near, off, near]]))), [[0, 255, 0]])

    def test_the_colour_of_a_cleared_pixel_is_kept(self):
        _, _, pixels = read_png(clear_white_background(png([[(251, 252, 253, 255), D]])))
        self.assertEqual(bytes(pixels[:4]), bytes((251, 252, 253, 0)))

    def test_a_picture_of_one_colour_that_is_not_white_is_left_alone(self):
        data = png([[D] * 4] * 4)
        self.assertEqual(clear_white_background(data), data)


if __name__ == "__main__":
    unittest.main()
