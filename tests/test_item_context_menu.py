"""The add-in's entries in Fusion's right-click menu: which are offered for a selection, and their registration and removal."""

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

from tests.without_fusion import fusion_modules_stubbed

MODULE_NAME = "item_context_menu"

with fusion_modules_stubbed():
    from src.ui import fusion_selection, item_context_menu


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.controls = mock.Mock()
        self.controls.itemById.return_value = None
        self.definitions = mock.Mock()
        self.event = types.SimpleNamespace(selectedEntities=["e1"], linearMarkingMenu=types.SimpleNamespace(controls=self.controls))
        patch = mock.patch.object(item_context_menu.adsk.core, "Application")
        application = patch.start()
        self.addCleanup(patch.stop)
        application.get.return_value.userInterface.commandDefinitions = self.definitions

    def command(self, ident, context="", root_only=False):
        return types.SimpleNamespace(command_id=ident, context=context, root_only=root_only)

    def fill(self, commands, drawing=False, component=object(), root=False):
        with mock.patch.object(item_context_menu.drawing_source, "active_drawing", return_value=object() if drawing else None), \
                mock.patch.object(item_context_menu.drawing_source, "selects_top_level", return_value=root), \
                mock.patch.object(fusion_selection, "selects_root", return_value=root), \
                mock.patch.object(fusion_selection, "component_of", return_value=component):
            item_context_menu._fill_menu(self.event, commands)

    def test_commands_are_added_under_one_line(self):
        self.fill([self.command("a"), self.command("b")])
        self.controls.addSeparator.assert_called_once_with(item_context_menu.LINE_ID)
        self.assertEqual(self.controls.addCommand.call_count, 2)
        self.assertEqual(fusion_selection.menu_selection, ["e1"])

    def test_a_selection_with_no_component_adds_nothing_in_a_design(self):
        self.fill([self.command("a")], component=None)
        self.controls.addCommand.assert_not_called()
        self.controls.addSeparator.assert_not_called()

    def test_an_empty_selection_adds_nothing_in_a_drawing(self):
        self.event.selectedEntities = []
        self.fill([self.command("a")], drawing=True)
        self.controls.addCommand.assert_not_called()

    def test_a_command_of_another_kind_of_document_or_for_the_root_only_is_removed(self):
        shown = mock.Mock()
        self.controls.itemById.side_effect = lambda ident: {"a": shown, "b": shown}.get(ident)
        self.fill([self.command("a", context="drawing"), self.command("b", root_only=True)])
        self.assertEqual(shown.deleteMe.call_count, 2)
        self.controls.addCommand.assert_not_called()

    def test_a_root_only_command_is_added_when_the_root_is_selected(self):
        self.fill([self.command("b", root_only=True)], root=True)
        self.controls.addCommand.assert_called_once()

    def test_a_command_already_in_the_menu_is_not_added_again(self):
        self.controls.itemById.side_effect = lambda ident: mock.Mock() if ident == "a" else None
        self.fill([self.command("a")])
        self.controls.addCommand.assert_not_called()
        self.controls.addSeparator.assert_not_called()


def load_with_real_handlers(module_name):
    """A fresh copy of the module whose Fusion handler base classes are real classes. Under the shared stand-in a class that subclasses one
    becomes a mock, so ``notify`` and ``dispose`` could not be run."""
    core = mock.MagicMock()
    core.MarkingMenuEventHandler = object
    core.ActiveSelectionEventHandler = object
    adsk = types.SimpleNamespace(core=core, fusion=mock.MagicMock())
    path = os.path.join(os.path.dirname(__file__), "..", "src", "ui", module_name + ".py")
    spec = importlib.util.spec_from_file_location("src.ui._real_handlers_" + module_name, path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"adsk": adsk, "adsk.core": core, "adsk.fusion": adsk.fusion}):
        spec.loader.exec_module(module)
    return module


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_with_real_handlers(MODULE_NAME)
        self.ui = mock.MagicMock()
        patcher = mock.patch.object(self.module, "define_command")
        self.define = patcher.start()
        self.addCleanup(patcher.stop)
        self.commands = [types.SimpleNamespace(command_id="a"), types.SimpleNamespace(command_id="b")]

    def test_each_command_is_defined_and_the_handler_listens_for_the_menu(self):
        menu = self.module.ItemContextMenu(self.ui, self.commands)
        self.assertEqual([c.args[1] for c in self.define.call_args_list], self.commands)
        self.ui.markingMenuDisplaying.add.assert_called_once_with(menu._handler)

    def test_disposing_removes_the_handler_and_the_definitions_that_exist(self):
        menu = self.module.ItemContextMenu(self.ui, self.commands)
        found = mock.Mock()
        self.ui.commandDefinitions.itemById.side_effect = lambda ident: found if ident == "a" else None
        menu.dispose()
        self.ui.markingMenuDisplaying.remove.assert_called_once_with(menu._handler)
        found.deleteMe.assert_called_once_with()

    def test_a_handler_that_cannot_be_removed_is_tolerated(self):
        menu = self.module.ItemContextMenu(self.ui, self.commands)
        self.ui.markingMenuDisplaying.remove.side_effect = RuntimeError("gone")
        menu.dispose()


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.module = load_with_real_handlers(MODULE_NAME)

    def test_the_menu_is_filled_for_the_arguments_cast_to_the_event(self):
        handler = self.module._MenuHandler(["a"])
        with mock.patch.object(self.module, "_fill_menu") as fill:
            self.module.adsk.core.MarkingMenuEventArgs.cast.return_value = "event"
            handler.notify("raw")
        fill.assert_called_once_with("event", ["a"])

    def test_a_failure_is_logged_not_raised_into_fusion(self):
        handler = self.module._MenuHandler(["a"])
        with mock.patch.object(self.module, "_fill_menu", side_effect=ValueError("bad")), \
                mock.patch.object(self.module.log, "exception") as logged:
            handler.notify("raw")
        logged.assert_called_once()


if __name__ == "__main__":
    unittest.main()
