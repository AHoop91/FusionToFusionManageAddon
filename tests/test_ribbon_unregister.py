"""What ``Ribbon.unregister`` removes: the add-in's panels in Fusion's own tab and in its own, its tab, its drop-down and its definitions."""

import sys
import types
import unittest


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
ribbon = None


def setUpModule():
    global ribbon
    for name in _NAMES:
        _saved[name] = sys.modules.get(name)
        sys.modules[name] = _Stub(name)
    for sub in ("core", "fusion", "drawing"):
        setattr(sys.modules["adsk"], sub, sys.modules["adsk." + sub])
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]
    from src.ui import ribbon as module
    ribbon = module


def tearDownModule():
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]
    for name, module in _saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class _Thing:
    """Something Fusion holds that can be deleted; says so in ``deleted``."""

    def __init__(self, item_id, deleted, label="", **parts):
        self.id = item_id
        self.name = label
        self._deleted = deleted
        self.__dict__.update(parts)

    def deleteMe(self):
        self._deleted.append(self.id)


class _Items:
    def __init__(self, items):
        self.items = list(items)

    def itemById(self, item_id):
        return next((i for i in self.items if i.id == item_id), None)

    def item(self, index):
        return self.items[index]

    @property
    def count(self):
        return len(self.items)


class UnregisterTest(unittest.TestCase):
    def setUp(self):
        self.deleted = []
        command = ribbon.RibbonCommand("cmd1", "One", "tip", lambda: None)
        self.panel = ribbon.RibbonPanel("pnl", "Panel", [ribbon.RibbonGroup([command])])
        self.panel_id = "pnl_ws"
        self.command = command

    def _thing(self, name, **parts):
        return _Thing(name, self.deleted, **parts)

    def _ui(self, tabs, menu_controls=(), definitions=()):
        workspace = types.SimpleNamespace(id="ws", toolbarTabs=_Items(tabs))
        toolbar = types.SimpleNamespace(controls=_Items(menu_controls))
        return types.SimpleNamespace(workspaces=_Items([workspace]), toolbars=_Items([_Thing("QAT", self.deleted, controls=toolbar.controls)]),
                                     commandDefinitions=_Items(definitions))

    def _tab(self, tab_id, label):
        return self._thing(tab_id, label=label, toolbarPanels=_Items([self._thing(self.panel_id)]))

    def test_panels_in_fusions_tab_and_the_own_tab_and_the_tab_are_removed(self):
        own = self._tab(ribbon.RIBBON_TAB_ID + "_ws", "Own")
        host = self._tab("host", "Manage")
        ui = self._ui([host, own], definitions=[self._thing("cmd1")])
        instance = ribbon.Ribbon(ui, {"ws": [self.panel]}, host_tab_name="manage")
        instance.unregister()
        self.assertEqual(self.deleted.count(self.panel_id), 2)   # one in each tab
        self.assertIn(ribbon.RIBBON_TAB_ID + "_ws", self.deleted)
        self.assertNotIn("host", self.deleted)   # Fusion's own tab stays
        self.assertIn("cmd1", self.deleted)

    def test_with_no_host_tab_only_the_own_tab_is_cleared(self):
        own = self._tab(ribbon.RIBBON_TAB_ID + "_ws", "Own")
        instance = ribbon.Ribbon(self._ui([own]), {"ws": [self.panel]})
        instance.unregister()
        self.assertEqual(self.deleted, [self.panel_id, ribbon.RIBBON_TAB_ID + "_ws"])

    def test_a_workspace_fusion_does_not_have_is_skipped(self):
        ui = self._ui([])
        instance = ribbon.Ribbon(ui, {"other": [self.panel]})
        instance.unregister()
        self.assertEqual(self.deleted, [])

    def test_the_toolbar_dropdown_is_removed(self):
        menu = ribbon.ToolbarMenu("menu1", "Menu", "", [self.command])
        dropdown = self._thing("menu1")
        ui = self._ui([], menu_controls=[dropdown])
        instance = ribbon.Ribbon(ui, {}, toolbar_menu=menu)
        instance.unregister()
        self.assertEqual(self.deleted, ["menu1"])

    def test_it_is_safe_to_call_twice(self):
        instance = ribbon.Ribbon(self._ui([]), {"ws": [self.panel]})
        instance.unregister()
        instance.unregister()


if __name__ == "__main__":
    unittest.main()
