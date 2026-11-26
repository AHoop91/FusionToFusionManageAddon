"""The Publish panel's real plan of an MBOM edit, sent by the real sender to the fake tenant.

The planner (``mbom-plan.js``, run with Node) decides which BOM operations an edit needs and in what order, and counts on that order being kept
(a line takes a number only once another has left it). The sender (``publish/sender.py``) sends them. Each is tested alone; this is the one test that
joins them, as a user's edit does. Each line the plan renumbers is sent one request, so the order they land in does not matter (Fusion Manage accepts two lines
at one number); the schedule here is the worst case, to keep it so. It needs Node, and is skipped without it.
"""

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.publish.states import DONE
from tests.fake_manage import FakeManage
from tests.publish_helpers import send, write_folder
from tests.test_publish_concurrency import Reversed

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def plans():
    done = subprocess.run([NODE, str(ROOT / "tests" / "js" / "emit_plans.js")], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@unittest.skipUnless(NODE, "Node is not installed")
class PlannerToTenantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plans = plans()

    def publish(self, name):
        scenario = copy.deepcopy(self.plans[name])
        tenant = FakeManage()
        parent = tenant.add_item("TOP-M")
        edge_of = {}
        for number, sequence in scenario["start"]:
            edge_of["e" + number] = tenant.add_line(parent, tenant.add_item(number), int(sequence))
        for op in scenario["operations"]:
            if op["op"] == "add":   # an item picked in Fusion Manage: it is there already
                if not tenant.count_of(op["number"]):
                    tenant.add_item(op["number"])
            if op.get("edge"):
                op["edge"] = edge_of[op["edge"]]
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        write_folder(root, {}, scenario["operations"])
        Reversed(tenant)
        return tenant, send(root, tenant), scenario

    @staticmethod
    def planned(scenario):
        """``(number, line number)`` of each line once the plan's operations were applied one after the other, as the planner means them."""
        held = {n: int(s) for n, s in scenario["start"]}
        for op in scenario["operations"]:
            if op["op"] == "remove":
                held.pop(op["number"], None)
            elif op["op"] in ("renumber", "add"):
                held[op["number"]] = int(op["sequence"])
        return list(held.items())

    def assert_published(self, name):
        for round_ in range(3):   # (the schedule is fixed; the rounds show it does not depend on luck)
            with self.subTest(scenario=name, round=round_):
                tenant, run, scenario = self.publish(name)
                lines = tenant.lines_of("TOP-M")
                self.assertEqual("".join(number for number, _s, _q in lines), scenario["order"], [row["detail"] for row in run.rows])
                self.assertEqual(sorted((n, s) for n, s, _q in lines), sorted(self.planned(scenario)))   # the numbers the plan gives, not only their order
                self.assertEqual({row["status"] for row in run.rows}, {DONE})

    def test_a_line_moved_to_the_front_where_every_number_it_takes_is_free(self):
        self.assert_published("front")

    def test_a_line_removed_and_another_appended(self):
        self.assert_published("remove_and_append")

    def test_a_line_inserted_in_the_middle(self):
        self.assert_published("insert")

    def test_two_lines_swapped(self):
        self.assert_published("swap")

    def test_several_lines_moved_to_the_front(self):
        self.assert_published("reverse")


if __name__ == "__main__":
    unittest.main()
