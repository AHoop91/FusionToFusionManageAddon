"""The Export window reads the permissions under one hub context, and reads them again when the hub or the settings have changed."""

import unittest
from unittest import mock

from src.config.models import ConnectionSettings
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


if __name__ == "__main__":
    unittest.main()
