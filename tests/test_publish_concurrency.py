"""Sending a publish folder with many requests in flight at once: what must hold however the threads interleave.

The fake tenant (``fake_manage``) is slowed a little for each request so the requests overlap, and the assertions are bounds and end states
that are true for every interleaving, never a particular order of threads.
"""

import shutil
import tempfile
import threading
import time
import unittest

from src.publish.sender import BOM_REQUESTS, WRITES, SendRun, load_plan
from src.publish.states import DONE
from tests.fake_manage import FakeManage
from tests.publish_helpers import add, create, edges_of, end_state, remove, renumber, send, write_folder


class Overlap:
    """Measures how many requests the fake tenant has in hand at once, and holds each a moment so that requests overlap."""

    def __init__(self, tenant: FakeManage, hold: float = 0.004) -> None:
        self.now = self.peak = 0
        self.lock = threading.Lock()
        self.hold = hold
        tenant.on_request, tenant.on_done = self.enter, self.leave

    def enter(self, method, path, body):
        if method == "GET":
            return
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
        time.sleep(self.hold)

    def leave(self, method, path, body):
        if method != "GET":
            with self.lock:
                self.now -= 1


class Reversed:
    """A worst-case schedule: of the writes that are in hand together, the one that arrived first is finished last. Any code that counts on
    requests that it sent together finishing in the order it sent them is wrong under this, and not by luck of timing."""

    def __init__(self, tenant: FakeManage, step: float = 0.012, window: int = 8) -> None:
        self.arrived, self.lock, self.step, self.window = 0, threading.Lock(), step, window
        tenant.on_request = self.arrive

    def arrive(self, method, path, body):
        if method == "GET":
            return
        with self.lock:
            self.arrived += 1
            turn = self.arrived
        time.sleep(max(0, self.window - turn) * self.step)


class TempCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)


class WritesInFlightTests(TempCase):
    def test_no_more_writes_are_in_flight_than_the_limit_across_items_and_parents(self):
        tenant = FakeManage()
        overlap = Overlap(tenant)
        items = {f"P{i}": create(f"P{i}") for i in range(12)} | {f"C{i}": create(f"C{i}") for i in range(12)}
        write_folder(self.root, items, [add(f"P{i}", f"C{j}", j + 1) for i in range(12) for j in range(4)])
        run = send(self.root, tenant)
        self.assertEqual(run.phase, DONE)
        self.assertLessEqual(overlap.peak, WRITES)
        self.assertEqual(len(tenant.writes()), 24 + 48)

    def test_one_parents_lines_use_no_more_threads_than_the_limit(self):
        self.assertLessEqual(BOM_REQUESTS, WRITES)


class IdsUnderConcurrencyTests(TempCase):
    def test_every_new_item_is_made_once_and_every_line_names_the_right_child(self):
        for round_ in range(5):
            with self.subTest(round=round_):
                shutil.rmtree(self.root, True)
                self.root = tempfile.mkdtemp()
                tenant = FakeManage()
                Overlap(tenant, 0.001)
                count = 25
                items = {f"P{i}": create(f"P{i}") for i in range(count)} | {f"C{i}": create(f"C{i}") for i in range(count)}
                write_folder(self.root, items, [add(f"P{i}", f"C{i}", 1) for i in range(count)])
                self.assertEqual(send(self.root, tenant).phase, DONE)
                state = end_state(tenant)
                self.assertEqual(set(state["numbers"].values()), {1})
                for i in range(count):   # P<i> holds C<i>, and no other: an id read for one item never lands on another
                    self.assertEqual(state["lines"][f"P{i}"], [(f"C{i}", 1, "1")])

    def test_many_parents_that_share_a_child_all_get_it(self):
        tenant = FakeManage()
        Overlap(tenant, 0.001)
        items = {f"P{i}": create(f"P{i}") for i in range(20)} | {"SHARED": create("SHARED")}
        write_folder(self.root, items, [add(f"P{i}", "SHARED", 1) for i in range(20)])
        self.assertEqual(send(self.root, tenant).phase, DONE)
        self.assertEqual({tuple(v) for k, v in end_state(tenant)["lines"].items() if k.startswith("P")}, {(("SHARED", 1, "1"),)})
        shared = tenant.id_of("SHARED")
        self.assertLessEqual(len(tenant.requests("GET", f"/items/{shared}")), 5)   # read again only by parents that first ask at the same moment (5 at a time), then kept


class OrderWithinAParentTests(TempCase):
    def test_a_position_is_freed_before_another_line_takes_it_whatever_the_interleaving(self):
        for round_ in range(5):
            with self.subTest(round=round_):
                shutil.rmtree(self.root, True)
                self.root = tempfile.mkdtemp()
                tenant = FakeManage()
                parent = tenant.add_item("A")
                kids = [tenant.add_item(f"K{i}") for i in range(9)]
                for i, kid in enumerate(kids[:6]):
                    tenant.add_line(parent, kid, i + 1)
                for i in range(3):
                    tenant.add_item(f"N{i}")
                edges = edges_of(tenant, "A")
                # K0..K2 leave; K3..K5 each move down into a position they left free; three new lines take the positions K3..K5 left.
                operations = ([remove("A", f"K{i}", i + 1, edges[(f"K{i}", i + 1)]) for i in range(3)]
                              + [renumber("A", f"K{i}", i + 1, i - 2, edges[(f"K{i}", i + 1)]) for i in range(3, 6)]
                              + [add("A", f"N{i}", i + 4) for i in range(3)])
                write_folder(self.root, {}, operations)
                Overlap(tenant, 0.003)
                run = send(self.root, tenant)
                self.assertEqual(run.phase, DONE, [r["detail"] for r in run.rows])
                methods = [m for m, p, b in tenant.writes()]
                last_delete = max(i for i, m in enumerate(methods) if m == "DELETE")
                first_patch = min(i for i, m in enumerate(methods) if m == "PATCH")
                last_patch = max(i for i, m in enumerate(methods) if m == "PATCH")
                first_post = min(i for i, m in enumerate(methods) if m == "POST")
                self.assertLess(last_delete, first_patch)
                self.assertLess(last_patch, first_post)
                self.assertEqual([s for _, s, _ in tenant.lines_of("A")], [1, 2, 3, 4, 5, 6])


class TwoSendsOfOneFolderTests(TempCase):
    @unittest.expectedFailure
    def test_two_sends_queued_before_either_ran_create_nothing_twice(self):
        """KNOWN GAP: a ``SendRun`` reads the send log when it is made, not when it runs, so a second send made before the first has run
        does not know what the first did, and creates the items again. The Retry action cannot queue two (``replace`` and ``get`` hide the
        failed run once it is retried) so this is latent, not reachable from the panel today."""
        tenant = FakeManage()
        write_folder(self.root, {f"P{i}": create(f"P{i}") for i in range(5)}, [])
        with tenant.serving():
            first = SendRun(self.root, load_plan(self.root), tenant.client())
            second = SendRun(self.root, load_plan(self.root), tenant.client())
            first.work()
            second.work()
        self.assertEqual(set(end_state(tenant)["numbers"].values()), {1})


if __name__ == "__main__":
    unittest.main()
