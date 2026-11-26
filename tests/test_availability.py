"""The gate switches a command off for the first reason it has, and writes to Fusion only when that reason changes."""

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
availability = ribbon = None


def setUpModule():
    global availability, ribbon
    for name in _NAMES:
        _saved[name] = sys.modules.get(name)
        sys.modules[name] = _Stub(name)
    for sub in ("core", "fusion", "drawing"):
        setattr(sys.modules["adsk"], sub, sys.modules["adsk." + sub])
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]
    from src.ui import availability as module, ribbon as ribbon_module
    availability, ribbon = module, ribbon_module


def tearDownModule():
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]
    for name, module in _saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class _Definitions:
    def __init__(self, ids):
        self.found = {i: types.SimpleNamespace(controlDefinition=types.SimpleNamespace(isEnabled=True), tooltip="") for i in ids}

    def itemById(self, command_id):
        return self.found.get(command_id)


def _command(command_id, **needs):
    return ribbon.RibbonCommand(command_id, command_id, "tip", lambda: None, **needs)


class SetupGateTest(unittest.TestCase):
    def _gate(self, commands, setup="", drawing="", portfolio="", destination="", known=None):
        definitions = _Definitions(known if known is not None else [c.command_id for c in commands])
        ui = types.SimpleNamespace(commandDefinitions=definitions)
        gate = availability.SetupGate(ui, commands, lambda: setup, lambda: drawing, lambda: portfolio, lambda: destination)
        return gate, definitions

    def test_a_command_with_no_needs_is_left_alone(self):
        free = _command("free")
        gate, definitions = self._gate([free], setup="not set up")
        gate.refresh()
        self.assertTrue(definitions.found["free"].controlDefinition.isEnabled)

    def test_the_first_reason_a_command_needs_wins(self):
        command = _command("both", needs_setup=True, needs_drawing=True)
        gate, definitions = self._gate([command], setup="no settings", drawing="drawing loading")
        gate.refresh()
        definition = definitions.found["both"]
        self.assertFalse(definition.controlDefinition.isEnabled)
        self.assertIn("no settings", definition.tooltip)
        self.assertNotIn("drawing loading", definition.tooltip)

    def test_each_command_looks_only_at_the_reasons_it_needs(self):
        commands = [_command("a", needs_drawing=True), _command("b", needs_portfolio=True), _command("c", needs_destination=True)]
        gate, definitions = self._gate(commands, setup="no settings", portfolio="no portfolio")
        gate.refresh()
        self.assertTrue(definitions.found["a"].controlDefinition.isEnabled)
        self.assertFalse(definitions.found["b"].controlDefinition.isEnabled)
        self.assertTrue(definitions.found["c"].controlDefinition.isEnabled)

    def test_a_command_is_enabled_again_with_its_own_tooltip(self):
        command = _command("a", needs_setup=True)
        problem = ["no settings"]
        definitions = _Definitions(["a"])
        gate = availability.SetupGate(types.SimpleNamespace(commandDefinitions=definitions), [command], lambda: problem[0])
        gate.refresh()
        problem[0] = ""
        gate.refresh()
        self.assertTrue(definitions.found["a"].controlDefinition.isEnabled)
        self.assertEqual(definitions.found["a"].tooltip, "tip")

    def test_only_a_change_is_written(self):
        command = _command("a", needs_setup=True)
        gate, definitions = self._gate([command], setup="no settings")
        gate.refresh()
        definitions.found["a"].tooltip = "touched"
        gate.refresh()
        self.assertEqual(definitions.found["a"].tooltip, "touched")

    def test_a_command_with_no_definition_is_skipped(self):
        gate, _ = self._gate([_command("a", needs_setup=True)], setup="no settings", known=[])
        gate.refresh()

    def test_a_failure_to_check_leaves_the_commands_as_they_are(self):
        command = _command("a", needs_setup=True)
        definitions = _Definitions(["a"])

        def broken():
            raise RuntimeError("down")

        availability.SetupGate(types.SimpleNamespace(commandDefinitions=definitions), [command], broken).refresh()
        self.assertTrue(definitions.found["a"].controlDefinition.isEnabled)


if __name__ == "__main__":
    unittest.main()
