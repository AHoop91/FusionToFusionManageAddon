import unittest
from unittest import mock

from src.sync.bom_compare import UNCOMPARED
from src.ui.actions import publish_actions


def row(number, level=0):
    return {"level": level, "item_number": number, "part_number": number, "quantity": "1"}


class DesignNotInFusionManageTests(unittest.TestCase):
    def test_no_item_for_the_design_leaves_its_lines_uncompared_and_asks_nothing_per_line(self):
        cfg = mock.Mock(workspace_id="242")
        fm = mock.Mock()
        with mock.patch.object(publish_actions, "read_and_compare_bom") as compare:
            data = publish_actions._compare_bom([row("A"), row("B", 1)], {"item_number": "TOP"}, cfg, fm, "", [])
        self.assertEqual([r["status"] for r in data["rows"]], [UNCOMPARED, UNCOMPARED])
        self.assertFalse(data["pick"])
        compare.assert_not_called()
        self.assertEqual(fm.method_calls, [])


if __name__ == "__main__":
    unittest.main()
