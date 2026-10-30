"""The Item panel reads an item, and answers the look-ups and uploads of the page, under the hub context the item was read under."""

import types
import unittest
from unittest import mock

from src.config.hub_context import capture_context
from src.config.models import ConnectionSettings
from src.config.workspace_models import ITEMS_KIND
from tests.hub_fixtures import config_of, items_workspace
from tests.without_fusion import fusion_modules_stubbed

with fusion_modules_stubbed():
    from src.ui import item_panel
    from src.ui.item_panel import ItemNotFound, ItemPanel


class Setup(unittest.TestCase):
    def setUp(self):
        self.config = config_of()
        self.host = mock.Mock(visible=True)
        self.tasks = mock.Mock()
        self.tasks.post.side_effect = lambda task: task()
        patch = mock.patch.object(item_panel, "_SelectionHandler")   # a subclass of Fusion's handler, which is not here
        patch.start()
        self.addCleanup(patch.stop)
        self.panel = ItemPanel(mock.MagicMock(), self.tasks, self.host, mock.Mock(), self.config, mock.Mock(), mock.Mock(), mock.Mock())
        self.started = []   # the worker threads: run by the test when it wants them to
        patch = mock.patch("threading.Thread", side_effect=lambda target, args=(), daemon=None: types.SimpleNamespace(
            start=lambda: self.started.append(lambda: target(*args))))
        patch.start()
        self.addCleanup(patch.stop)
        self.stamp = capture_context(self.config).stamp

    def run_threads(self):
        while self.started:
            self.started.pop(0)()

    def change_settings(self, tenant="other", workspace="999", hub="hub2"):
        self.config.hub_id = hub
        self.config.effective_settings.return_value = ConnectionSettings(client_id="c", tenant=tenant)
        self.config.config.workspaces = {ITEMS_KIND: items_workspace(workspace)}


class ReadTests(Setup):
    def read_with(self, outcome):
        self.panel._number = "PN-1"
        with mock.patch.object(self.panel, "_read", side_effect=outcome) as read:
            self.panel._start()
            self.run_threads()
        return read

    def test_the_item_is_read_under_the_context_taken_when_the_read_started(self):
        self.panel._number = "PN-1"
        with mock.patch.object(self.panel, "_read", return_value={"item_id": "9"}) as read:
            self.panel._start()
            self.change_settings()   # before the worker thread has run
            self.run_threads()
        self.assertEqual(read.call_args.args[2].tenant, "acme")
        self.assertEqual(read.call_args.args[2].cfg.workspace_id, "242")

    def test_the_view_and_the_answer_carry_the_stamp_the_page_sends_back(self):
        self.read_with([{"item_id": "9"}])
        state = self.panel._status({})
        self.assertEqual((state["stamp"], state["view"]["stamp"]), (self.stamp, self.stamp))

    def test_an_answer_that_is_not_an_item_carries_it_too(self):
        self.read_with(ItemNotFound("PN-1"))
        self.assertEqual((self.panel._status({})["missing"], self.panel._status({})["stamp"]), ("PN-1", self.stamp))

    def test_settings_that_cannot_be_read_are_the_answer_and_nothing_is_read(self):
        self.config.effective_settings.side_effect = RuntimeError("shared file unreadable")
        self.panel._number = "PN-1"
        self.panel._start()
        self.assertEqual(self.started, [])
        self.assertIn("shared file unreadable", self.panel._status({})["message"])
        self.assertEqual(self.host.send.call_args[0][0], "get_item_view")


class RequestTests(Setup):
    def ask(self, **extra):
        return {"request": "r1", "workspace_id": "242", "item_id": "9", "stamp": self.stamp, **extra}

    def test_a_request_under_the_stamp_of_the_item_shown_is_made_under_the_settings_active(self):
        self.assertEqual(self.panel._context_of(self.ask()).tenant, "acme")

    def test_a_request_made_before_the_hub_or_workspace_changed_is_refused(self):
        self.change_settings()
        with self.assertRaisesRegex(ValueError, "settings changed"):
            self.panel._context_of(self.ask())
        with self.assertRaisesRegex(ValueError, "settings changed"):
            self.panel._context_of({})

    def test_a_refused_look_up_is_answered_with_why_and_reads_nothing(self):
        self.change_settings()
        with mock.patch.object(item_panel, "WhereUsedService") as service:
            self.assertEqual(self.panel._where_used_load(self.ask()), {"started": True})
            self.run_threads()
        service.assert_not_called()
        answer = self.panel._lookup_result({"request": "r1"})
        self.assertFalse(answer["ok"] or answer["pending"])
        self.assertIn("settings changed", answer["message"])
        self.assertEqual(self.host.send.call_args[0][0], "where_used_result")   # pushed, not left for the page to ask

    def test_a_look_up_reads_under_the_context_taken_when_it_was_asked_for(self):
        with mock.patch.object(item_panel, "WhereUsedService") as service, mock.patch.object(item_panel, "FmClient") as client:
            service.return_value.read.return_value = {"rows": []}
            self.panel._where_used_load(self.ask())
            self.change_settings()   # before the worker thread has run
            self.run_threads()
        self.assertEqual(client.call_args.args[0].tenant, "acme")
        service.assert_called_once()

    def test_a_design_check_uses_the_workspace_of_the_context_not_the_one_active_now(self):
        seen = []
        check = mock.Mock(side_effect=lambda shown: seen.append(shown.cfg.workspace_id) or {"state": "ok"})
        with mock.patch.object(item_panel, "_active_ref"), mock.patch.object(item_panel, "FmClient"), \
                mock.patch.object(item_panel, "FusionGraphQlClient"), mock.patch.object(self.panel._numbers, "model_of"):
            self.panel._design_check(self.ask(), check, "sync_check_result")
            self.change_settings()
            self.run_threads()
        self.assertEqual(seen, ["242"])

    def test_a_choice_is_kept_for_the_workspace_of_the_context(self):
        self.panel._number = "PN-1"
        with mock.patch.object(self.panel, "_start"):
            self.panel._choose_item(self.ask(item_id="9"))
        hits = [{"id": "8", "descriptor": "PN-1 - Bolt"}, {"id": "9", "descriptor": "PN-1 - Nut"}]
        self.assertEqual(self.panel._choices.resolve("242", "PN-1", hits)[0]["id"], "9")   # kept for the workspace the item was read in
        self.assertIsNone(self.panel._choices.resolve("999", "PN-1", hits)[0])

    def test_a_choice_made_before_the_settings_changed_is_refused(self):
        self.panel._number = "PN-1"
        self.change_settings()
        with mock.patch.object(self.panel, "_start") as start, self.assertRaisesRegex(ValueError, "settings changed"):
            self.panel._choose_item(self.ask(item_id="9"))
        start.assert_not_called()

    def test_an_upload_is_made_under_the_context_the_item_was_read_under(self):
        self.panel._number = "PN-1"
        self.panel._uploads = mock.Mock()
        with mock.patch.object(item_panel, "_active_selection", return_value=[]), mock.patch.object(item_panel, "pick"):
            self.panel._upload_for_item(mock.Mock(), self.ask())
        context = self.panel._uploads.from_panel.call_args.args[1]
        self.assertEqual((context.tenant, context.cfg.workspace_id), ("acme", "242"))

    def test_an_upload_asked_for_after_the_settings_changed_is_refused(self):
        self.panel._number = "PN-1"
        self.panel._uploads = mock.Mock()
        self.change_settings()
        with self.assertRaisesRegex(ValueError, "settings changed"):
            self.panel._upload_for_item(mock.Mock(), self.ask())
        self.panel._uploads.from_panel.assert_not_called()


class SettingsChangedTests(Setup):
    def shown(self):
        self.panel._number = "PN-1"
        self.panel._state["stamp"] = self.stamp

    def test_an_item_read_under_other_settings_is_read_again(self):
        self.shown()
        self.change_settings()
        with mock.patch.object(self.panel, "_reload") as reload:
            self.panel._settings_changed()
        reload.assert_called_once()

    def test_an_item_read_under_the_settings_still_active_is_left_alone(self):
        self.shown()
        with mock.patch.object(self.panel, "_reload") as reload:
            self.panel._settings_changed()
        reload.assert_not_called()

    def test_a_panel_that_shows_nothing_or_is_hidden_is_left_alone(self):
        self.change_settings()
        with mock.patch.object(self.panel, "_reload") as reload:
            self.panel._settings_changed()   # shows no item
            self.shown()
            self.host.visible = False
            self.panel._settings_changed()
        reload.assert_not_called()

    def test_settings_that_cannot_be_read_do_not_make_it_read_again_for_ever(self):
        self.shown()
        self.config.effective_settings.side_effect = RuntimeError("unreadable")
        with mock.patch.object(self.panel, "_reload") as reload:
            self.panel._settings_changed()
            self.panel._state["stamp"] = ""   # what a read that could not take the settings leaves
            self.panel._settings_changed()
        reload.assert_called_once()


class WarmTests(Setup):
    def test_the_workspace_that_is_prepared_is_that_of_the_context(self):
        context = capture_context(self.config)
        self.change_settings()
        with mock.patch.object(item_panel, "ItemViewService") as service, mock.patch.object(item_panel, "FmClient") as client:
            self.panel._warm(context)
        self.assertEqual(client.call_args.args[0].tenant, "acme")
        self.run_threads()
        service.return_value.prepare.assert_called_once_with("242")

    def test_nothing_is_prepared_without_a_context_or_an_items_workspace(self):
        self.panel._warm(None)
        self.config.config.workspaces = {ITEMS_KIND: items_workspace("")}
        self.panel._warm(capture_context(self.config))
        self.assertEqual(self.started, [])


if __name__ == "__main__":
    unittest.main()
