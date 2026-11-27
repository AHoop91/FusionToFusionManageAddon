"""The Export window reads the permissions under one hub context, and reads them again when the hub or the settings have changed."""

import unittest
from unittest import mock

from src.config.models import ConnectionSettings
from src.fm.client import FmApiError
from src.config.workspace_models import ITEMS_KIND, WorkspaceConfig
from tests.hub_fixtures import auth_of, capture, config_of
from tests.without_fusion import fusion_modules_stubbed

with fusion_modules_stubbed():
    from src.ui import export_dialog
    from src.ui.export_dialog import ExportDialog


class Setup(unittest.TestCase):
    def setUp(self):
        self.config = config_of()
        self.panel = mock.Mock()
        self.dialog = ExportDialog(mock.Mock(), mock.Mock(), mock.Mock(), self.config, auth_of(), self.panel)
        for patch in (mock.patch.object(export_dialog, "_document", return_value=""),
                      mock.patch.object(export_dialog, "formats_for", return_value=[]),
                      mock.patch.object(export_dialog, "describe")):
            patch.start()
            self.addCleanup(patch.stop)

    def change_settings(self):
        self.config.hub_id = "hub2"
        self.config.effective_settings.return_value = ConnectionSettings(client_id="c", tenant="other")

    def context(self):
        with mock.patch("threading.Thread") as thread:
            self.dialog._context({})
        return thread


class ShowSelectedTests(Setup):
    def test_the_component_that_was_right_clicked_is_selected_again_before_the_window_opens(self):
        order = []
        with mock.patch.object(export_dialog.fusion_selection, "restore_menu_selection", side_effect=lambda: order.append("select")),                 mock.patch.object(self.dialog, "show", side_effect=lambda: order.append("show")):
            self.dialog.show_selected()
        self.assertEqual(order, ["select", "show"])


class SetupReasonTests(Setup):
    def test_a_destination_is_set_up_when_the_connection_and_the_workspace_are_complete(self):
        reasons, context = self.dialog._setup()
        self.assertEqual(reasons, {"item": "", "component": ""})
        self.assertEqual(context.tenant, "acme")

    def test_settings_that_cannot_be_read_are_the_reason_of_both_destinations_and_give_no_context(self):
        self.config.effective_settings.side_effect = RuntimeError("shared file unreadable")
        reasons, context = self.dialog._setup()
        self.assertEqual(reasons, {"item": "shared file unreadable", "component": "shared file unreadable"})
        self.assertIsNone(context)

    def test_the_ribbon_button_is_on_when_a_destination_is_set_up(self):
        self.assertEqual(self.dialog.problem(), "")

    def test_the_ribbon_button_is_on_when_only_the_component_is_set_up(self):
        with mock.patch.object(self.dialog, "_setup", return_value=({"item": "not set up", "component": ""}, None)):
            self.assertEqual(self.dialog.problem(), "")

    def test_the_ribbon_button_is_off_with_the_reason_when_no_destination_is_set_up(self):
        self.config.effective_settings.side_effect = RuntimeError("shared file unreadable")
        self.assertEqual(self.dialog.problem(), "shared file unreadable")


class ItemTurnedOffTests(Setup):
    def test_the_item_is_not_offered_and_only_the_component_counts_for_the_ribbon_button(self):
        self.config.config.workspaces = {ITEMS_KIND: WorkspaceConfig(workspace_id="999", enabled=False)}
        with mock.patch("threading.Thread"):
            shown = self.dialog._context({})
        self.assertEqual({d["key"]: d["hidden"] for d in shown["destinations"]}, {"item": True, "component": False})
        self.assertEqual(self.dialog.problem(), "")

    def test_the_ribbon_button_gives_the_reason_of_the_component_not_of_the_item_turned_off(self):
        setup = {"item": "turned off", "component": "complete the connection"}
        with mock.patch.object(self.dialog, "_setup", return_value=(setup, mock.Mock(items_off=True))):
            self.assertEqual(self.dialog.problem(), "complete the connection")

    def test_the_item_is_offered_when_it_is_on(self):
        with mock.patch("threading.Thread"):
            shown = self.dialog._context({})
        self.assertFalse(any(d["hidden"] for d in shown["destinations"]))


class AppRefusedTests(Setup):
    def client(self, error=None):
        client = mock.Mock()
        client.get_json.side_effect = error
        return client

    def test_the_app_is_refused_when_the_list_of_workspaces_is_a_401(self):
        self.assertTrue(ExportDialog._app_refused(self.client(FmApiError("x", 401))))

    def test_it_is_not_when_the_user_is_only_refused_a_workspace_or_the_list_is_read(self):
        self.assertFalse(ExportDialog._app_refused(self.client(FmApiError("x", 404))))
        self.assertFalse(ExportDialog._app_refused(self.client()))
        self.assertFalse(ExportDialog._app_refused(self.client(RuntimeError("down"))))


class ReadAgainTests(Setup):
    def test_the_permissions_are_read_once_under_the_context_active_when_the_window_asks(self):
        thread = self.context()
        self.assertEqual(thread.call_args.kwargs["args"][1].tenant, "acme")
        self.assertTrue(self.dialog._checking)

    def test_what_was_read_under_the_settings_still_active_is_kept(self):
        self.dialog._checked({"item": "", "component": ""}, capture(self.config).stamp)
        self.assertEqual(self.context().call_count, 0)

    def test_what_was_read_under_other_settings_is_dropped_and_read_again(self):
        self.dialog._checked({"item": "", "component": ""}, capture(self.config).stamp)
        self.change_settings()
        with mock.patch("threading.Thread") as thread:
            shown = self.dialog._context({})
        self.assertEqual(thread.call_args.kwargs["args"][1].tenant, "other")
        self.assertTrue(all(d["checking"] for d in shown["destinations"]))   # the old answer is not shown meanwhile

    def test_what_was_read_for_another_user_is_dropped_and_read_again(self):
        self.dialog._checked({"item": "", "component": ""}, capture(self.config).stamp)
        self.dialog._auth.session.return_value = 2
        with mock.patch("threading.Thread") as thread:
            shown = self.dialog._context({})
        thread.assert_called_once()
        self.assertTrue(all(d["checking"] for d in shown["destinations"]))

    def test_an_export_asked_for_under_other_settings_than_those_read_is_refused(self):
        self.dialog._checked({"item": "", "component": ""}, capture(self.config).stamp)
        self.change_settings()
        with mock.patch.object(export_dialog, "formats_for", return_value=["step"]), self.assertRaisesRegex(ValueError, "settings changed"):
            self.dialog._run({"format": "step", "destination": "item"})
        self.panel.export.assert_not_called()

    def test_the_item_permission_is_asked_about_the_workspace_of_the_context(self):
        context = capture(self.config)
        with mock.patch.object(export_dialog, "denial", return_value="") as denial:
            self.config.config.workspaces = {ITEMS_KIND: WorkspaceConfig(workspace_id="999")}   # changed since
            self.dialog._item_denial(mock.Mock(), context)
        self.assertEqual(denial.call_args[0][1], "242")


class ChosenItemTests(Setup):
    def run_export(self, destination, item=""):
        self.dialog._checked({"item": "", "component": ""}, capture(self.config).stamp)
        with mock.patch.object(export_dialog, "formats_for", return_value=["step"]):
            return self.dialog._run({"format": "step", "destination": destination, "target": "PN-1", "item": item})

    def test_an_export_to_an_item_needs_one_the_table_listed(self):
        self.panel.knows_item.return_value = False
        with self.assertRaisesRegex(ValueError, "Choose the item"):
            self.run_export("item", "99")
        self.panel.export.assert_not_called()

    def test_the_item_the_table_listed_goes_on_to_the_export(self):
        self.panel.knows_item.return_value = True
        self.run_export("item", "17195")
        self.panel.knows_item.assert_called_once_with("PN-1", "17195")
        self.panel.export.assert_called_once_with("step", "item", "PN-1", "17195")

    def test_an_export_to_the_component_takes_no_item(self):
        self.run_export("component", "17195")
        self.panel.knows_item.assert_not_called()
        self.panel.export.assert_called_once_with("step", "component", "PN-1", "")

    def test_the_attached_files_are_read_for_the_item_chosen_and_the_answer_names_it(self):
        self.panel.knows_item.return_value = True
        sent = []
        self.dialog._push = lambda event, result: sent.append((event, result))
        with mock.patch.object(export_dialog, "formats_for", return_value=["step"]):
            self.dialog._files({"format": "step", "destination": "item", "target": "PN-1", "item": "17195"})
        self.assertEqual(self.panel.export_files.call_args.args[:2], ("step", "item"))
        self.assertEqual(self.panel.export_files.call_args.args[-1], "17195")
        self.panel.export_files.call_args.args[3]({"state": "ok"})
        self.assertEqual(sent, [("export_files_found", {"state": "ok", "format": "step", "destination": "item", "item": "17195"})])


if __name__ == "__main__":
    unittest.main()
