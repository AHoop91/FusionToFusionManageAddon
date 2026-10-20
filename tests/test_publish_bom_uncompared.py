"""A design that is not in Fusion Manage has nothing to compare its lines with: they are left uncompared, with no request per line."""

import sys
import types
import unittest
from unittest import mock

from src.sync.bom_compare import UNCOMPARED


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
publish_actions = None


def setUpModule():
    global publish_actions
    for name in _NAMES:
        _saved[name] = sys.modules.get(name)
        sys.modules[name] = _Stub(name)
    for sub in ("core", "fusion", "drawing"):
        setattr(sys.modules["adsk"], sub, sys.modules["adsk." + sub])
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]   # imported again below, against the stand-ins
    from src.ui.actions import publish_actions as module
    publish_actions = module


def tearDownModule():
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]   # so no other test meets a module built on the stand-ins
    for name, module in _saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def row(number, level=0):
    return {"level": level, "item_number": number, "part_number": number, "quantity": "1"}


class DesignNotInFusionManageTests(unittest.TestCase):
    def test_no_item_for_the_design_leaves_its_lines_uncompared_and_asks_nothing_per_line(self):
        cfg = mock.Mock(workspace_id="242")
        fm = mock.Mock()
        with mock.patch.object(publish_actions, "read_and_compare_bom") as compare:
            data = publish_actions._compare_bom([row("A"), row("B", 1)], {"item_number": "TOP"}, cfg, fm, "", [])
        self.assertEqual([r["status"] for r in data["rows"]], [UNCOMPARED, UNCOMPARED])
        self.assertFalse(data["pick"])
        compare.assert_not_called()
        self.assertEqual(fm.method_calls, [])


if __name__ == "__main__":
    unittest.main()
