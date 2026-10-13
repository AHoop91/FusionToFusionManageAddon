"""An attachment is opened with its program only when it is a known safe type; anything else shows its folder."""

import os
import sys
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


_NAMES = ("adsk", "adsk.core", "adsk.fusion", "adsk.drawing")
_saved = {}
item_panel = None


def setUpModule():
    global item_panel
    for name in _NAMES:
        _saved[name] = sys.modules.get(name)
        sys.modules[name] = _Stub(name)
    for sub in ("core", "fusion", "drawing"):
        setattr(sys.modules["adsk"], sub, sys.modules["adsk." + sub])
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]   # imported again below, against the stand-ins
    from src.ui import item_panel as module
    item_panel = module


def tearDownModule():
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]   # so no other test meets a module built on the stand-ins
    for name, module in _saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class OpenFileTests(unittest.TestCase):
    def opened(self, path):
        with mock.patch.object(item_panel.os, "startfile", create=True) as start:
            item_panel._open_file(path)
        return start.call_args[0][0]

    def test_known_safe_type_opens_itself(self):
        self.assertEqual(self.opened(os.path.join("d", "a.pdf")), os.path.join("d", "a.pdf"))

    def test_programs_and_disguised_programs_show_their_folder(self):
        for name in ("a.exe", "a.exe.", "a.exe ", "a.exe. .", "a.docm", "a.url", "a.html", "noext"):
            self.assertEqual(self.opened(os.path.join("d", name)), "d", name)


if __name__ == "__main__":
    unittest.main()
