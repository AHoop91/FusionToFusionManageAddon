"""The Add Items picker's reads and the poll for their answers. Run: python -m unittest discover tests"""

import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from src.fm.client import FmApiError
from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import search_actions
    from src.ui.actions.search_actions import (BAD_SEARCH, KEPT_ANSWERS, NO_ITEM, OPTIONS_PAGE, PickerReads,
                                               register_search_actions)
    from src.ui.message_bridge import MessageBridge


class Setup(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(config=SimpleNamespace(workspaces={search_actions.ITEMS_KIND: SimpleNamespace(workspace_id="242")}))
        self.client = object()
        self.queued = []   # the reads, run by the test when it wants them to
        self.reads = PickerReads(self.config, lambda: self.client, self.queued.append)
        self.items, self.workspace = mock.Mock(), mock.Mock()
        for patch in (mock.patch.object(search_actions, "ItemSearchService", self.items),
                      mock.patch.object(search_actions, "WorkspaceService", self.workspace)):
            patch.start()
            self.addCleanup(patch.stop)

    def finish(self):
        while self.queued:
            self.queued.pop(0)()


class ItemsTests(Setup):
    def test_a_request_is_pending_until_its_read_is_done_then_its_answer_is_kept_under_its_token(self):
        self.items.return_value.page.return_value = {"items": [1], "raw": 1}
        pending = self.reads.items({"token": "t1", "text": "bolt", "offset": 20, "revision": 3, "item_id": "9"})
        self.assertEqual((pending["token"], pending["pending"], pending["ok"]), ("t1", True, False))
        self.assertEqual(self.reads.status({"token": "t1"})["pending"], True)
        self.finish()
        done = self.reads.status({"token": "t1"})
        self.assertEqual((done["pending"], done["ok"], done["result"]), (False, True, {"items": [1], "raw": 1}))
        self.items.return_value.page.assert_called_once_with("242", "9", "bolt", None, 20, 3)

    def test_what_is_not_a_number_is_read_as_nothing_and_a_missing_revision_is_the_latest(self):
        self.reads.items({"token": "t1", "offset": "abc", "revision": "x"})
        self.finish()
        self.assertEqual(self.items.return_value.page.call_args[0][4:], (0, 1))

    def test_a_negative_offset_is_the_start(self):
        self.reads.items({"token": "t1", "offset": -5})
        self.finish()
        self.assertEqual(self.items.return_value.page.call_args[0][4], 0)

    def test_without_the_items_workspace_it_says_so_and_reads_nothing(self):
        self.config.config.workspaces = {}
        answer = self.reads.items({"token": "t1"})
        self.assertEqual((answer["pending"], answer["ok"], answer["message"]), (False, False, NO_ITEM))
        self.assertEqual(self.queued, [])


class MembersTests(Setup):
    def test_a_design_not_yet_in_fusion_manage_has_no_members_and_nothing_is_read(self):
        answer = self.reads.members({"token": "t1"})
        self.assertEqual((answer["ok"], answer["result"]), (True, {"ids": [], "numbers": []}))
        self.assertEqual(self.queued, [])

    def test_the_members_of_the_item_are_read(self):
        self.items.return_value.members.return_value = {"ids": ["1"], "numbers": ["A"]}
        self.reads.members({"token": "t1", "item_id": "9"})
        self.finish()
        self.assertEqual(self.reads.status({"token": "t1"})["result"], {"ids": ["1"], "numbers": ["A"]})
        self.items.return_value.members.assert_called_once_with("242", "9")

    def test_without_the_items_workspace_it_says_so(self):
        self.config.config.workspaces = {}
        self.assertEqual(self.reads.members({"token": "t1", "item_id": "9"})["message"], NO_ITEM)


class FieldsAndOptionsTests(Setup):
    def test_the_filterable_fields_of_the_items_workspace_are_read(self):
        self.workspace.return_value.filterable_fields.return_value = [{"id": "F"}]
        self.reads.fields({"token": "t1"})
        self.finish()
        self.assertEqual(self.reads.status({"token": "t1"})["result"], {"fields": [{"id": "F"}]})
        self.assertTrue(self.workspace.return_value.filterable_fields.call_args[0][0].endswith("/242"))

    def test_without_the_items_workspace_no_fields_are_read(self):
        self.config.config.workspaces = {}
        self.assertEqual(self.reads.fields({"token": "t1"})["message"], NO_ITEM)

    def test_a_page_of_picklist_options_is_read(self):
        self.workspace.return_value.options_page.return_value = {"options": []}
        self.reads.options({"token": "t1", "lookup": "/lookups/1", "offset": "50", "text": "re"})
        self.finish()
        self.workspace.return_value.options_page.assert_called_once_with("/lookups/1", 50, OPTIONS_PAGE, "re")

    def test_no_picklist_named_is_told_and_nothing_is_read(self):
        answer = self.reads.options({"token": "t1"})
        self.assertEqual(answer["message"], "No picklist was named.")
        self.assertEqual(self.queued, [])


class FailureTests(Setup):
    def failed(self, error):
        self.items.return_value.page.side_effect = error
        self.reads.items({"token": "t1"})
        self.finish()
        return self.reads.status({"token": "t1"})

    def test_a_search_fusion_manage_cannot_read_gets_the_advice_to_check_the_filter(self):
        answer = self.failed(FmApiError("bad", 400))
        self.assertEqual((answer["ok"], answer["pending"], answer["message"]), (False, False, BAD_SEARCH))

    def test_any_other_refusal_is_told_as_it_is(self):
        self.assertEqual(self.failed(FmApiError("down", 503))["message"], "down")

    def test_an_unexpected_failure_is_told_by_its_message_or_its_kind(self):
        self.assertEqual(self.failed(ValueError("odd"))["message"], "odd")
        self.assertEqual(self.failed(RuntimeError())["message"], "RuntimeError")

    def test_a_client_that_cannot_be_made_leaves_no_answer_pending(self):
        def refuse():
            raise RuntimeError("no settings")

        reads = PickerReads(self.config, refuse, self.queued.append)
        with self.assertRaises(RuntimeError):
            reads.items({"token": "t1"})
        self.assertEqual(reads.status({"token": "t1"})["message"], "Unknown request.")
        self.assertEqual(self.queued, [])


class TokenTests(Setup):
    def test_a_request_without_a_token_is_refused(self):
        for call in (self.reads.items, self.reads.members, self.reads.fields, self.reads.options, self.reads.status):
            with self.assertRaisesRegex(ValueError, "no token"):
                call({})

    def test_an_unknown_token_is_told_as_unknown(self):
        answer = self.reads.status({"token": "never"})
        self.assertEqual((answer["pending"], answer["ok"], answer["message"]), (False, False, "Unknown request."))

    def test_only_the_latest_answers_are_kept(self):
        for number in range(KEPT_ANSWERS + 5):
            self.reads.items({"token": str(number)})
        self.assertEqual(self.reads.status({"token": "0"})["message"], "Unknown request.")
        self.assertTrue(self.reads.status({"token": str(KEPT_ANSWERS + 4)})["pending"])

    def test_the_answer_handed_back_is_a_copy(self):
        self.reads.items({"token": "t1"})
        self.reads.status({"token": "t1"})["pending"] = False
        self.assertTrue(self.reads.status({"token": "t1"})["pending"])


class OneAtATimeTests(Setup):
    def test_two_reads_never_run_at_the_same_time(self):
        inside, overlapped = [], []
        release = threading.Event()

        def slow(workspace, item_id):
            inside.append(1)
            if len(inside) > 1:
                overlapped.append(True)
            release.wait(5)
            inside.pop()
            return {}

        self.items.return_value.members.side_effect = slow
        self.reads.members({"token": "a", "item_id": "1"})
        self.reads.members({"token": "b", "item_id": "2"})
        threads = [threading.Thread(target=work, daemon=True) for work in self.queued]
        for thread in threads:
            thread.start()
        release.set()
        for thread in threads:
            thread.join(5)
        self.assertEqual(overlapped, [])
        self.assertTrue(self.reads.status({"token": "a"})["ok"] and self.reads.status({"token": "b"})["ok"])


class RegisterTests(unittest.TestCase):
    def test_every_action_is_registered(self):
        bridge = MessageBridge()
        with mock.patch.object(search_actions, "PickerReads") as reads:
            register_search_actions(bridge, mock.Mock(), mock.Mock())
        reads.return_value.status.return_value = {"token": "t"}
        self.assertEqual(bridge.dispatch("search_status", '{"token": "t"}')["result"], {"token": "t"})
        for action in ("search_items", "search_members", "search_fields", "search_options"):
            self.assertTrue(bridge.dispatch(action, '{"token": "t"}')["ok"], action)


if __name__ == "__main__":
    unittest.main()
