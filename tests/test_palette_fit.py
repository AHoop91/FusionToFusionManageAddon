"""``palette_host._fit``: where a floating palette starts so it is centred in Fusion's viewport and never runs off the screen."""

import importlib
import sys
import types
import unittest
from unittest import mock


def _load_palette_host():
    """``palette_host`` imports ``adsk`` (only in Fusion): it is imported against a stand-in that is gone again afterwards."""
    core = types.ModuleType("adsk.core")
    core.HTMLEventHandler = type("HTMLEventHandler", (), {})
    adsk = types.ModuleType("adsk")
    adsk.core = core
    with mock.patch.dict(sys.modules, {"adsk": adsk, "adsk.core": core}):
        return importlib.import_module("src.ui.palette_host")


palette_host = _load_palette_host()
MARGIN = palette_host.EDGE_MARGIN


class FitTests(unittest.TestCase):
    def test_a_palette_that_fits_is_centred(self):
        self.assertEqual(palette_host._fit(100, 1000, 400), 400)

    def test_a_palette_wider_than_the_span_ends_a_margin_short_of_the_far_edge(self):
        left = palette_host._fit(100, 500, 700)
        self.assertEqual(left + 700, 100 + 500 - MARGIN)

    def test_a_palette_that_would_end_inside_the_margin_is_moved_back(self):
        left = palette_host._fit(0, 1000, 950)   # centred it would end at 975, inside the margin
        self.assertEqual(left, 1000 - 950 - MARGIN)

    def test_a_palette_that_fits_with_room_to_spare_is_not_moved_by_the_margin(self):
        size = 1000 - 2 * MARGIN
        self.assertEqual(palette_host._fit(0, 1000, size), MARGIN)


if __name__ == "__main__":
    unittest.main()
