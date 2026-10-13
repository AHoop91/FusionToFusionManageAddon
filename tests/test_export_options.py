import unittest

from src.fm.components import link_ids
from src.ui.export_options import DWG, DXF, FORMATS, PDF, STEP, describe, formats_for


class FormatsTests(unittest.TestCase):
    def test_a_design_makes_a_step_file_and_a_drawing_a_pdf_dwg_or_dxf(self):
        self.assertEqual(formats_for("design"), [STEP])
        self.assertEqual(formats_for("drawing"), [PDF, DWG, DXF])
        self.assertEqual(formats_for(""), [])

    def test_describe_carries_what_the_page_shows(self):
        self.assertEqual(describe(DWG), {"key": "dwg", "label": "DWG", "ext": ".dwg"})
        for key in FORMATS:
            self.assertEqual(describe(key)["ext"], FORMATS[key].extension)


class LinkIdsTests(unittest.TestCase):
    def test_workspace_and_item_of_an_api_link(self):
        self.assertEqual(link_ids("/api/v3/workspaces/242/items/15727"), ("242", "15727"))
        self.assertEqual(link_ids("https://t.autodeskplm360.net/api/v3/workspaces/9/items/12/views/1"), ("9", "12"))

    def test_nothing_to_read(self):
        self.assertEqual(link_ids(""), ("", ""))
        self.assertEqual(link_ids("/api/v3/workspaces/242"), ("", ""))


if __name__ == "__main__":
    unittest.main()
