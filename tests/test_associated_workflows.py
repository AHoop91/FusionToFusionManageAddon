import unittest

from src.fm.associated_workflows import parse_associated_workflows
from src.fm.client import FmApiError

BASE = "https://acme.autodeskplm360.net"
ENTRY = {
    "item": {"link": "/api/v3/workspaces/142/items/15740", "urn": "urn:adsk.plm:tenant.workspace.item:ACME.142.15740",
             "title": "LCO-000055 - Revised Assembly Types", "currentState": "Closed"},
    "workflow-state": {"title": "Complete"},
    "last-workflow-history": {"created": "2026-10-07T11:15:36.658-04:00", "user": {"title": "Pat"},
                              "workflowTransition": {"title": "Close"}, "comments": "Done"},
}


class AssociatedWorkflowTests(unittest.TestCase):
    def test_row_from_an_entry(self):
        (row,) = parse_associated_workflows([ENTRY], BASE)
        self.assertEqual(row["title"], "LCO-000055 - Revised Assembly Types")
        self.assertEqual(row["state"], "Complete")
        self.assertEqual(row["last"], {"date": "2026-10-07T11:15:36.658-04:00", "user": "Pat", "action": "Close", "comments": "Done"})
        self.assertIn("/plm/workspaces/142/items/", row["url"])

    def test_state_falls_back_to_the_items_own(self):
        (row,) = parse_associated_workflows([{**ENTRY, "workflow-state": None}], BASE)
        self.assertEqual(row["state"], "Closed")

    def test_nothing_referencing_the_item(self):
        self.assertEqual(parse_associated_workflows(None, BASE), [])
        self.assertEqual(parse_associated_workflows([{}], BASE), [])

    def test_unexpected_answer_is_an_error(self):
        with self.assertRaises(FmApiError):
            parse_associated_workflows({"unexpected": 1}, BASE)


if __name__ == "__main__":
    unittest.main()
