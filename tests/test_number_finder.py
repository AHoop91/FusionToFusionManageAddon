"""Finding the item number of a component on a worker thread, then acting on it on the UI thread (``NumberFinder``)."""

import types
import unittest
from unittest import mock

from src.core.cancel import Cancelled
from src.core.i18n import t
from tests.without_fusion import fusion_modules_stubbed
from tests.test_item_panel_context import Setup, fusion_selection, number_finder

with fusion_modules_stubbed():
    from src.ui.item_numbers import NoItemNumber, Subject


class FindTests(Setup):
    def setUp(self):
        super().setUp()
        self.then = mock.Mock()
        self.options = number_finder.FindOptions(ref="ref")
        for target, name in ((self.panel._finder, "warm"),):
            patcher = mock.patch.object(target, name)
            self.warm = patcher.start()
            self.addCleanup(patcher.stop)
        self.box = self.panel._ui.messageBox

    def find(self, number="PN-1", options=None):
        self.panel._finder.find(number, self.then, options or self.options)

    def resolve_with(self, outcome):
        patcher = mock.patch.object(self.panel._numbers, "resolve", side_effect=outcome)
        resolve = patcher.start()
        self.addCleanup(patcher.stop)
        return resolve

    def test_an_empty_part_number_tells_the_user_what_to_select_and_reads_nothing(self):
        self.find("")
        self.assertEqual(self.box.call_args.args[0], t("app.select_component"))
        self.assertEqual(self.started, [])

    def test_a_quiet_find_of_nothing_says_nothing(self):
        self.find("", number_finder.FindOptions(quiet=True))
        self.box.assert_not_called()
        self.assertEqual(self.started, [])

    def test_the_item_number_is_read_on_a_worker_and_handed_on_on_the_ui_thread(self):
        subject = Subject("ITEM-1", "PN-1")
        resolve = self.resolve_with([subject])
        self.find()
        self.then.assert_not_called()   # nothing happens before the worker runs
        self.run_threads()
        self.then.assert_called_once_with(subject)
        self.assertEqual(resolve.call_args.args[:2], ("ref", "PN-1"))
        self.warm.assert_called_once()

    def test_the_ref_is_worked_out_when_none_is_given(self):
        self.resolve_with([Subject("ITEM-1", "PN-1")])
        with mock.patch.object(fusion_selection, "part_ref", return_value="worked out") as make:
            self.find(options=number_finder.FindOptions())
        make.assert_called_once_with("PN-1")
        self.run_threads()

    def test_a_fresh_find_reads_the_layout_of_the_workspace_again(self):
        with mock.patch.object(number_finder, "ItemViewService") as service:
            self.find(options=number_finder.FindOptions(ref="ref", fresh=True))
            service.forget.assert_called_once_with()
            service.reset_mock()
            self.find()
            service.forget.assert_not_called()

    def test_a_find_that_was_cancelled_says_nothing(self):
        self.resolve_with(Cancelled())
        self.find()
        self.run_threads()
        self.then.assert_not_called()
        self.box.assert_not_called()

    def test_a_failure_is_shown_in_a_message_box_and_logged(self):
        self.resolve_with(ValueError("no model"))
        with mock.patch.object(number_finder.log, "exception") as logged:
            self.find()
            self.run_threads()
        self.assertEqual(self.box.call_args.args[0], "no model")
        logged.assert_called_once()
        self.then.assert_not_called()

    def test_a_failure_is_given_to_the_function_that_asks_for_it(self):
        fail = mock.Mock()
        self.resolve_with(ValueError("no model"))
        self.find(options=number_finder.FindOptions(ref="ref", fail=fail))
        self.run_threads()
        fail.assert_called_once_with("no model")
        self.box.assert_not_called()

    def test_a_quiet_failure_is_only_logged(self):
        self.resolve_with(ValueError("no model"))
        with mock.patch.object(number_finder.log, "exception") as logged:
            self.find(options=number_finder.FindOptions(ref="ref", quiet=True))
            self.run_threads()
        logged.assert_called_once()
        self.box.assert_not_called()

    def test_a_component_with_no_item_number_is_logged_as_information(self):
        self.resolve_with(NoItemNumber("not published"))
        with mock.patch.object(number_finder.log, "exception") as failed, mock.patch.object(number_finder.log, "info") as info:
            self.find()
            self.run_threads()
        failed.assert_not_called()
        info.assert_called_once()
        self.assertEqual(self.box.call_args.args[0], "not published")

    def test_an_error_with_no_text_shows_its_type(self):
        self.resolve_with(KeyError())
        with mock.patch.object(number_finder.log, "exception"):
            self.find()
            self.run_threads()
        self.assertEqual(self.box.call_args.args[0], "KeyError")


class HasNumberTests(Setup):
    def test_a_number_is_a_component_to_look_up(self):
        self.assertTrue(self.panel._finder.has_number("PN-1"))
        self.panel._ui.messageBox.assert_not_called()

    def test_no_number_says_what_to_select_unless_quiet(self):
        self.assertFalse(self.panel._finder.has_number("", quiet=True))
        self.panel._ui.messageBox.assert_not_called()
        self.assertFalse(self.panel._finder.has_number(""))
        self.assertEqual(self.panel._ui.messageBox.call_args.args[0], t("app.select_component"))


class FollowTests(Setup):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(self.panel._finder, "find")
        self.find = patcher.start()
        self.addCleanup(patcher.stop)

    def follow(self, number):
        with mock.patch.object(fusion_selection, "active_selection", return_value=["e"]), \
                mock.patch.object(fusion_selection, "selected_component_number", return_value=number):
            self.panel._follow_selection()

    def test_a_hidden_panel_does_not_follow(self):
        self.host.visible = False
        self.follow("PN-2")
        self.find.assert_not_called()

    def test_a_selection_with_no_number_leaves_the_panel_as_it_is(self):
        self.follow("")
        self.find.assert_not_called()

    def test_the_part_already_shown_is_not_found_again(self):
        self.panel._part = "PN-2"
        self.follow("PN-2")
        self.find.assert_not_called()

    def test_another_part_is_found_quietly_and_replaces_the_find_before(self):
        self.follow("PN-2")
        options = self.find.call_args.args[2]
        self.assertTrue(options.quiet)
        self.assertIs(options.cancel, self.panel._follow.token)
        self.assertEqual(self.find.call_args.args[0], "PN-2")

    def test_opening_the_selected_reads_the_selection_fresh(self):
        with mock.patch.object(fusion_selection, "selected_part_number", return_value="PN-3"):
            self.panel.open_selected()
        self.assertEqual(self.find.call_args.args[0], "PN-3")
        self.assertTrue(self.find.call_args.args[2].fresh)
        self.assertEqual(self.find.call_args.args[1], self.panel._open)


if __name__ == "__main__":
    unittest.main()
