"""The Item panel's reads of what is open in Fusion: which attached files are out of date."""

import unittest
from unittest import mock

from tests.test_item_panel_context import Setup, fusion_selection, item_panel


class FilesFreshnessTests(Setup):
    def ask(self, *names):
        return {"files": [{"name": name, "updated": "2026-01-01T00:00:00Z"} for name in names] + ["not a file"]}

    def freshness(self, payload, drawing=False, design=True, state="stale"):
        with mock.patch.object(fusion_selection.drawing_source, "active_drawing", return_value=object() if drawing else None), \
                mock.patch.object(fusion_selection, "open_design", return_value=object() if design else None), \
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


if __name__ == "__main__":
    unittest.main()
