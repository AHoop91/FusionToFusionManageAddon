"""The Item panel's reads of what is open in Fusion: the names Export shows, which attached files are out of date, and the right-click menu."""

import types
import unittest
from unittest import mock

from tests.test_item_panel_context import Setup, item_panel


def component(name, description="", ident="c1"):
    return types.SimpleNamespace(name=name, description=description, id=ident)


def design_of(root):
    return types.SimpleNamespace(rootComponent=root)


class ExportNamesTests(Setup):
    def test_the_top_of_a_design_loses_the_version_of_the_document(self):
        root = component("Bracket v12", "A bracket", "root")
        with mock.patch.object(item_panel.drawing_source, "active_drawing", return_value=None), \
                mock.patch.object(item_panel, "_active_selection", return_value=[]), \
                mock.patch.object(item_panel, "_open_design", return_value=design_of(root)):
            self.assertEqual(self.panel.export_names(), ("Bracket", "A bracket"))

    def test_a_selected_component_keeps_its_name(self):
        root, part = component("Bracket v12", "", "root"), component("Bolt v2", " M6 ", "part")
        with mock.patch.object(item_panel.drawing_source, "active_drawing", return_value=None), \
                mock.patch.object(item_panel, "_active_selection", return_value=["entity"]), \
                mock.patch.object(item_panel, "_component_of", return_value=part), \
                mock.patch.object(item_panel, "_open_design", return_value=design_of(root)):
            self.assertEqual(self.panel.export_names(), ("Bolt v2", "M6"))

    def test_a_drawing_gives_the_name_of_the_design_it_shows(self):
        root = component("Frame v3", "A frame", "root")
        with mock.patch.object(item_panel.drawing_source, "active_drawing", return_value=object()), \
                mock.patch.object(item_panel.drawing_source, "referenced_design", return_value=design_of(root)):
            self.assertEqual(self.panel.export_names(), ("Frame", "A frame"))

    def test_nothing_open_gives_no_names(self):
        with mock.patch.object(item_panel.drawing_source, "active_drawing", return_value=None), \
                mock.patch.object(item_panel, "_active_selection", return_value=[]), \
                mock.patch.object(item_panel, "_open_design", return_value=None):
            self.assertEqual(self.panel.export_names(), ("", ""))

    def test_a_design_that_cannot_be_read_gives_no_names(self):
        with mock.patch.object(item_panel.drawing_source, "active_drawing", side_effect=RuntimeError("gone")):
            self.assertEqual(self.panel.export_names(), ("", ""))


class FilesFreshnessTests(Setup):
    def ask(self, *names):
        return {"files": [{"name": name, "updated": "2026-01-01T00:00:00Z"} for name in names] + ["not a file"]}

    def freshness(self, payload, drawing=False, design=True, state="stale"):
        with mock.patch.object(item_panel.drawing_source, "active_drawing", return_value=object() if drawing else None), \
                mock.patch.object(item_panel, "_open_design", return_value=object() if design else None), \
                mock.patch.object(self.panel, "_saved_source", return_value={}) as saved, \
                mock.patch.object(item_panel, "compare_freshness", return_value={"state": state, "message": "older"}):
            self.panel._number = "PN-1"
            answer = self.panel._files_freshness(payload)
        return answer, saved

    def test_the_step_file_of_a_design_saved_since_is_out_of_date(self):
        answer, _saved = self.freshness(self.ask("PN-1.step", "PN-1.pdf", "other.step"))
        self.assertEqual(answer, {"stale": {"PN-1.step": "older"}})

    def test_the_files_of_a_drawing_are_pdf_dwg_and_dxf(self):
        answer, _saved = self.freshness(self.ask("PN-1.pdf", "PN-1.dwg", "PN-1.dxf", "PN-1.step"), drawing=True)
        self.assertEqual(set(answer["stale"]), {"PN-1.pdf", "PN-1.dwg", "PN-1.dxf"})

    def test_a_current_file_is_not_listed(self):
        answer, _saved = self.freshness(self.ask("PN-1.step"), state="current")
        self.assertEqual(answer, {"stale": {}})

    def test_a_file_changed_since_the_last_save_is_listed(self):
        answer, _saved = self.freshness(self.ask("PN-1.step"), state="unsaved")
        self.assertEqual(set(answer["stale"]), {"PN-1.step"})

    def test_no_document_or_no_matching_file_reads_nothing(self):
        answer, _saved = self.freshness(self.ask("PN-1.step"), design=False)
        self.assertEqual(answer, {"stale": {}})
        answer, saved = self.freshness(self.ask("other.step"))
        self.assertEqual(answer, {"stale": {}})
        saved.assert_not_called()


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.controls = mock.Mock()
        self.controls.itemById.return_value = None
        self.definitions = mock.Mock()
        self.event = types.SimpleNamespace(selectedEntities=["e1"], linearMarkingMenu=types.SimpleNamespace(controls=self.controls))
        patch = mock.patch.object(item_panel.adsk.core, "Application")
        application = patch.start()
        self.addCleanup(patch.stop)
        application.get.return_value.userInterface.commandDefinitions = self.definitions

    def command(self, ident, context="", root_only=False):
        return types.SimpleNamespace(command_id=ident, context=context, root_only=root_only)

    def fill(self, commands, drawing=False, component=object(), root=False):
        with mock.patch.object(item_panel.drawing_source, "active_drawing", return_value=object() if drawing else None), \
                mock.patch.object(item_panel.drawing_source, "selects_top_level", return_value=root), \
                mock.patch.object(item_panel, "_selects_root", return_value=root), \
                mock.patch.object(item_panel, "_component_of", return_value=component):
            item_panel._fill_menu(self.event, commands)

    def test_commands_are_added_under_one_line(self):
        self.fill([self.command("a"), self.command("b")])
        self.controls.addSeparator.assert_called_once_with(item_panel.LINE_ID)
        self.assertEqual(self.controls.addCommand.call_count, 2)
        self.assertEqual(item_panel._menu_selection, ["e1"])

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


if __name__ == "__main__":
    unittest.main()
