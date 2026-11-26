"""What the Export window needs from Fusion and Fusion Manage: what is exported, its names, the item number read ahead, the look at the
attached files, and the export itself (``ExportPanel``)."""

import types
import unittest
from unittest import mock

from src.core.cancel import Cancelled
from src.core.i18n import t
from tests.test_item_panel_context import Setup, export_panel, fusion_selection
from tests.without_fusion import fusion_modules_stubbed

with fusion_modules_stubbed():
    from src.ui.item_numbers import Subject


def component(name, description="", ident="c1"):
    return types.SimpleNamespace(name=name, description=description, id=ident)


def design_of(root):
    return types.SimpleNamespace(rootComponent=root)


class ExportSetup(Setup):
    def setUp(self):
        super().setUp()
        self.exporter = self.panel.exporter
        self.shared_uploads = self.exporter._uploads
        self.uploads = mock.Mock()
        self.exporter._uploads = self.uploads
        self.subject = Subject("ITEM-1", "PN-1")

    def resolve_with(self, outcome):
        patcher = mock.patch.object(self.panel._numbers, "resolve", side_effect=outcome)
        resolve = patcher.start()
        self.addCleanup(patcher.stop)
        return resolve


class ExportNamesTests(ExportSetup):
    def test_the_top_of_a_design_loses_the_version_of_the_document(self):
        root = component("Bracket v12", "A bracket", "root")
        with mock.patch.object(fusion_selection.drawing_source, "active_drawing", return_value=None), \
                mock.patch.object(fusion_selection, "active_selection", return_value=[]), \
                mock.patch.object(fusion_selection, "open_design", return_value=design_of(root)):
            self.assertEqual(self.exporter.export_names(), ("Bracket", "A bracket"))

    def test_a_selected_component_keeps_its_name(self):
        root, part = component("Bracket v12", "", "root"), component("Bolt v2", " M6 ", "part")
        with mock.patch.object(fusion_selection.drawing_source, "active_drawing", return_value=None), \
                mock.patch.object(fusion_selection, "active_selection", return_value=["entity"]), \
                mock.patch.object(fusion_selection, "component_of", return_value=part), \
                mock.patch.object(fusion_selection, "open_design", return_value=design_of(root)):
            self.assertEqual(self.exporter.export_names(), ("Bolt v2", "M6"))

    def test_a_drawing_gives_the_name_of_the_design_it_shows(self):
        root = component("Frame v3", "A frame", "root")
        with mock.patch.object(fusion_selection.drawing_source, "active_drawing", return_value=object()), \
                mock.patch.object(fusion_selection.drawing_source, "referenced_design", return_value=design_of(root)):
            self.assertEqual(self.exporter.export_names(), ("Frame", "A frame"))

    def test_nothing_open_gives_no_names(self):
        with mock.patch.object(fusion_selection.drawing_source, "active_drawing", return_value=None), \
                mock.patch.object(fusion_selection, "active_selection", return_value=[]), \
                mock.patch.object(fusion_selection, "open_design", return_value=None):
            self.assertEqual(self.exporter.export_names(), ("", ""))

    def test_a_design_that_cannot_be_read_gives_no_names(self):
        with mock.patch.object(fusion_selection.drawing_source, "active_drawing", side_effect=RuntimeError("gone")):
            self.assertEqual(self.exporter.export_names(), ("", ""))


class ExportTargetTests(ExportSetup):
    def target(self, drawing, drawing_number=("", ""), part_number=""):
        with mock.patch.object(fusion_selection.drawing_source, "active_drawing", return_value=object() if drawing else None), \
                mock.patch.object(fusion_selection.drawing_source, "top_level_number", return_value=drawing_number), \
                mock.patch.object(fusion_selection, "selected_part_number", return_value=part_number):
            return self.exporter.export_target()

    def test_a_drawing_with_a_number_exports_its_top(self):
        self.assertEqual(self.target(True, ("DRW-1", "")), ("DRW-1", ""))

    def test_a_drawing_with_no_number_says_it_is_not_ready(self):
        self.assertEqual(self.target(True, ("", "loading")), ("", t("app.drawing_not_ready", reason="loading")))

    def test_a_design_exports_the_selected_part(self):
        self.assertEqual(self.target(False, part_number="PN-2"), ("PN-2", ""))

    def test_a_design_with_nothing_to_export_says_what_to_select(self):
        self.assertEqual(self.target(False), ("", t("app.select_component")))


class ExportStateTests(ExportSetup):
    def test_the_ref_of_a_part_is_read_once_until_the_window_is_reset(self):
        with mock.patch.object(fusion_selection, "part_ref", side_effect=["first", "second", "third"]) as make:
            self.assertEqual(self.exporter._export_ref("PN-1"), "first")
            self.assertEqual(self.exporter._export_ref("PN-1"), "first")   # the selection may change while the window is open
            self.assertEqual(self.exporter._export_ref("PN-2"), "second")
            self.exporter.reset_export()
            self.assertEqual(self.exporter._export_ref("PN-1"), "third")
        self.assertEqual(make.call_count, 3)

    def test_the_last_save_is_read_once_for_a_number_and_document(self):
        with mock.patch.object(export_panel, "saved_state", side_effect=[{"n": 1}, {"n": 2}]) as read, \
                mock.patch.object(fusion_selection, "active_selection", return_value=[]):
            self.assertEqual(self.exporter._export_state("PN-1"), {"n": 1})
            self.assertEqual(self.exporter._export_state("PN-1"), {"n": 1})
            self.assertEqual(self.exporter._export_state("PN-2"), {"n": 2})
        self.assertEqual(read.call_count, 2)

    def test_reset_forgets_what_was_read_and_what_an_earlier_window_was_reading(self):
        before = self.exporter.export_token
        with mock.patch.object(self.panel._numbers, "forget_files") as forget, \
                mock.patch.object(export_panel, "saved_state", side_effect=[{"n": 1}, {"n": 2}]), \
                mock.patch.object(fusion_selection, "active_selection", return_value=[]):
            self.exporter._export_state("PN-1")
            self.exporter.reset_export()
            self.assertEqual(self.exporter._export_state("PN-1"), {"n": 2})
        forget.assert_called_once_with()
        self.assertTrue(before.cancelled)
        self.assertIsNot(self.exporter.export_token, before)

    def test_cancelling_replaces_the_token_and_ends_the_old_one(self):
        before = self.exporter.export_token
        self.exporter.cancel_export()
        self.assertTrue(before.cancelled)
        self.assertFalse(self.exporter.export_token.cancelled)


class WarmExportTargetTests(ExportSetup):
    def setUp(self):
        super().setUp()
        self.found, self.thumbnail = mock.Mock(), mock.Mock()
        for name, value in (("export_target", ("PN-1", "")),):
            patcher = mock.patch.object(self.exporter, name, return_value=value)
            self.target = patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(fusion_selection, "part_ref", return_value="ref")
        patcher.start()
        self.addCleanup(patcher.stop)

    def warm(self):
        self.exporter.warm_export_target(self.found, self.thumbnail)
        self.run_threads()

    def test_nothing_to_export_reads_nothing(self):
        self.target.return_value = ("", "why")
        self.warm()
        self.assertEqual(self.started, [])

    def test_settings_that_cannot_be_read_read_nothing(self):
        self.config.effective_settings.side_effect = RuntimeError("unreadable")
        self.warm()
        self.assertEqual(self.started, [])

    def test_the_number_then_the_thumbnail_are_told_and_the_attached_files_are_warmed(self):
        self.resolve_with([self.subject])
        with mock.patch.object(self.panel._numbers, "thumbnail_url", return_value="url") as thumbnail:
            self.warm()
        self.found.assert_called_once_with("PN-1", "ITEM-1")
        self.thumbnail.assert_called_once_with("PN-1", "url")
        self.assertEqual(thumbnail.call_args.args[:2], ("ref", "PN-1"))
        self.uploads.warm_component.assert_called_once()
        self.assertEqual(self.uploads.warm_component.call_args.args[:2], (self.subject, "ref"))

    def test_a_number_that_cannot_be_read_leaves_the_title_empty(self):
        self.resolve_with(ValueError("no model"))
        self.warm()
        self.found.assert_called_once_with("PN-1", "")
        self.thumbnail.assert_called_once_with("PN-1", "")
        self.uploads.warm_component.assert_not_called()

    def test_a_cancelled_read_says_nothing(self):
        self.resolve_with(Cancelled())
        self.warm()
        self.found.assert_not_called()
        self.thumbnail.assert_not_called()

    def test_a_thumbnail_that_cannot_be_read_leaves_the_picture_empty(self):
        self.resolve_with([self.subject])
        with mock.patch.object(self.panel._numbers, "thumbnail_url", side_effect=ValueError("none")):
            self.warm()
        self.thumbnail.assert_called_once_with("PN-1", "")
        self.uploads.warm_component.assert_called_once()

    def test_a_cancelled_thumbnail_ends_the_read(self):
        self.resolve_with([self.subject])
        with mock.patch.object(self.panel._numbers, "thumbnail_url", side_effect=Cancelled()):
            self.warm()
        self.thumbnail.assert_not_called()
        self.uploads.warm_component.assert_not_called()


class ExportFilesTests(ExportSetup):
    def setUp(self):
        super().setUp()
        self.done = mock.Mock()
        for target, name, value in ((fusion_selection, "part_ref", "ref"), (export_panel, "saved_state", {"saved": True}),
                                    (fusion_selection, "active_selection", [])):
            patcher = mock.patch.object(target, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def files(self, number="PN-1"):
        self.exporter.export_files("pdf", "dest", number, self.done)
        self.run_threads()

    def test_nothing_to_export_is_unavailable(self):
        self.files("")
        self.done.assert_called_once_with({"state": "unavailable", "message": t("app.nothing_to_export")})
        self.assertEqual(self.started, [])

    def test_settings_that_cannot_be_read_are_unavailable_with_the_reason(self):
        self.config.effective_settings.side_effect = RuntimeError("unreadable")
        self.files()
        self.assertEqual(self.done.call_args.args[0]["state"], "unavailable")
        self.assertIn("unreadable", self.done.call_args.args[0]["message"])
        self.assertEqual(self.started, [])

    def test_the_look_is_given_the_file_name_an_export_gives(self):
        self.resolve_with([Subject("ITEM/1", "PN-1")])
        self.uploads.preview.return_value = {"state": "new"}
        self.files()
        self.done.assert_called_once_with({"state": "new"})
        args = self.uploads.preview.call_args.args
        self.assertEqual((args[0], args[1], args[2], args[3], args[4]), ("dest", Subject("ITEM/1", "PN-1"), "ref", "ITEM_1.pdf", {"saved": True}))

    def test_a_cancelled_look_says_nothing(self):
        self.resolve_with(Cancelled())
        self.files()
        self.done.assert_not_called()

    def test_another_failure_is_unavailable_with_its_text(self):
        self.resolve_with(ValueError("no model"))
        self.files()
        self.done.assert_called_once_with({"state": "unavailable", "message": "no model"})


class ExportTests(ExportSetup):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(self.panel._finder, "find")
        self.find = patcher.start()
        self.addCleanup(patcher.stop)
        for target, name, value in ((fusion_selection, "part_ref", "ref"), (fusion_selection, "active_selection", []),
                                    (export_panel, "pick", None), (export_panel, "export_job", "job")):
            patcher = mock.patch.object(target, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_nothing_to_export_raises_the_problem(self):
        with mock.patch.object(self.exporter, "export_target", return_value=("", "pick one")), self.assertRaisesRegex(ValueError, "pick one"):
            self.exporter.export("pdf", "dest")
        self.find.assert_not_called()

    def test_an_upload_already_under_way_raises(self):
        self.uploads.begin_in_window.return_value = None
        with self.assertRaisesRegex(ValueError, t("app.upload_busy")):
            self.exporter.export("pdf", "dest", "PN-1")
        self.find.assert_not_called()

    def test_the_number_the_window_shows_is_found_and_the_upload_continues_in_the_window(self):
        self.uploads.begin_in_window.return_value = "context"
        self.exporter.export("pdf", "dest", "PN-1")
        number, then, options = self.find.call_args.args
        self.assertEqual(number, "PN-1")
        self.assertEqual((options.ref, options.fail), ("ref", self.uploads.fail_in_window))
        then(self.subject)
        self.uploads.continue_in_window.assert_called_once_with("job", "context", self.subject, "dest", "ref")

    def test_the_selected_target_is_used_when_no_number_is_passed(self):
        self.uploads.begin_in_window.return_value = "context"
        with mock.patch.object(self.exporter, "export_target", return_value=("PN-9", "")):
            self.exporter.export("pdf", "dest")
        self.assertEqual(self.find.call_args.args[0], "PN-9")


class SharedStateTests(ExportSetup):
    def test_the_export_window_shares_the_collaborators_of_the_panel(self):
        for name in ("_contexts", "_numbers", "_finder"):
            self.assertIs(getattr(self.exporter, name), getattr(self.panel, name))
        self.assertIs(self.shared_uploads, self.panel._uploads)


class ExportTokenTests(ExportSetup):
    def test_closing_the_window_ends_what_it_was_reading(self):
        token = self.exporter.export_token
        self.panel.dispose()
        self.assertTrue(token.cancelled)


if __name__ == "__main__":
    unittest.main()
