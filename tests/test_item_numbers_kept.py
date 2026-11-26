"""Item numbers found once are kept in a file, so a later session needs no Data Model read."""

import os
import sys
import tempfile
import types
import unittest
from unittest import mock


class _Stub(types.ModuleType):
    """A stand-in for Fusion's ``adsk`` modules: any name in it is an empty class."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = type(name, (), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, value)
        return value


_NAMES = ("adsk", "adsk.core", "adsk.fusion")
_saved = {}
item_numbers = None


def setUpModule():
    global item_numbers
    for name in _NAMES:
        _saved[name] = sys.modules.get(name)
        sys.modules[name] = _Stub(name)
    for sub in ("core", "fusion"):
        setattr(sys.modules["adsk"], sub, sys.modules["adsk." + sub])
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]
    from src.ui import item_numbers as module
    item_numbers = module


def tearDownModule():
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]
    for name, module in _saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class KeptItemNumbersTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "kept", "item_numbers.json")
        self.ref = item_numbers.DesignRef("model", "2024-01-01")

    def _numbers(self):
        # No config or sign-in: a read of the Data Model would fail, so an answer can only come from the file.
        return item_numbers.ItemNumbers(remembered_path=self.path)

    def test_kept_across_sessions(self):
        subject = item_numbers.Subject("IT-1", "PN-1")
        item_numbers._Remembered(self.path).add(self.ref, "pn-1 ", subject)
        self.assertEqual(self._numbers().resolve(self.ref, "PN-1"), subject)

    def test_a_new_version_is_read_again(self):
        item_numbers._Remembered(self.path).add(self.ref, "PN-1", item_numbers.Subject("IT-1", "PN-1"))
        self.assertIsNone(item_numbers._Remembered(self.path).get(item_numbers.DesignRef("model", "2024-02-02"), "PN-1"))

    def test_the_oldest_go_first(self):
        kept = item_numbers._Remembered(self.path)
        kept.LIMIT = 2
        for n in ("A", "B", "C"):
            kept.add(self.ref, n, item_numbers.Subject("IT-" + n, n))
        self.assertIsNone(kept.get(self.ref, "A"))
        self.assertIsNotNone(kept.get(self.ref, "C"))

    def test_an_unreadable_file_is_ignored(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(item_numbers._Remembered(self.path).get(self.ref, "PN-1"))


class ResolveTest(unittest.TestCase):
    """What ``resolve`` makes of the Data Model's answer (the reads are stood in for)."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.numbers = item_numbers.ItemNumbers(remembered_path=os.path.join(folder.name, "item_numbers.json"))
        self.numbers.reads = mock.Mock()
        patcher = mock.patch.object(item_numbers, "FusionGraphQlClient")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ref = item_numbers.DesignRef("model", "2024-01-01")

    def _resolve(self, matches, part_number="PN-1", is_design=False):
        with mock.patch.object(item_numbers.ItemNumbers, "_matching", return_value=(is_design, matches)):
            return self.numbers.resolve(self.ref, part_number)

    def test_the_item_number_of_a_component(self):
        subject = self._resolve([{"id": "c", "item_number": " IT-1 ", "part_number": "PN-1"}])
        self.assertEqual(subject, item_numbers.Subject("IT-1", "PN-1"))
        self.assertEqual(self.numbers._remembered.get(self.ref, "PN-1"), subject)   # kept for next time

    def test_the_design_itself_is_named_by_its_own_part_number(self):
        subject = self._resolve([{"id": "c", "item_number": "IT-0", "part_number": "TOP"}], part_number="", is_design=True)
        self.assertEqual(subject, item_numbers.Subject("IT-0", "TOP"))

    def test_a_part_number_not_in_the_design_is_refused(self):
        with self.assertRaises(item_numbers.NoItemNumber):
            self._resolve([])

    def test_several_item_numbers_are_refused(self):
        with self.assertRaises(item_numbers.NoItemNumber):
            self._resolve([{"id": "a", "item_number": "IT-1", "part_number": "PN-1"}, {"id": "b", "item_number": "IT-2", "part_number": "PN-1"}])

    def test_a_component_not_published_is_refused_and_not_kept(self):
        with self.assertRaises(item_numbers.NoItemNumber):
            self._resolve([{"id": "a", "item_number": " ", "part_number": "PN-1"}])
        self.assertIsNone(self.numbers._remembered.get(self.ref, "PN-1"))

    def test_an_unsaved_design_is_refused(self):
        with self.assertRaises(item_numbers.NoItemNumber):
            self.numbers.resolve(item_numbers.DesignRef("", ""), "PN-1")


if __name__ == "__main__":
    unittest.main()
