"""Items go to Fusion Manage together, not one at a time, within the limit on requests in flight."""

import json
import os
import tempfile
import threading
import time
import unittest

from src.fm.client import FmApiError
from src.publish.send_log import SEND_LOG
from src.publish.sender import WRITES, Dispatcher, SendRun, load_plan
from src.publish.states import DONE
from tests.test_sender import FakeFm, create, write_folder

LATENCY = 0.05   # seconds a request takes


class Slow(FakeFm):
    """A client whose requests take a while, and which notes how many were under way at once."""

    def __init__(self, refuse="", hold=None):
        super().__init__(refuse)
        self.hold, self.under_way, self.most = hold, 0, 0
        self._guard = threading.Lock()

    def send_json(self, method, path, body=None):
        with self._guard:
            self.under_way += 1
            self.most = max(self.most, self.under_way)
        try:
            if self.hold is not None and (body or {}).get("n") == "A":
                self.hold.wait(5)
            else:
                time.sleep(LATENCY)
            return super().send_json(method, path, body)
        finally:
            with self._guard:
                self.under_way -= 1


def logged(path):
    with open(os.path.join(path, SEND_LOG), encoding="utf-8") as handle:
        return json.load(handle)


class DispatcherParallelTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = self.dir.name

    def send_together(self, dispatcher, numbers):
        failures = []

        def send(number):
            try:
                dispatcher.send_item(number, create(number))
            except FmApiError as exc:
                failures.append((number, exc))

        threads = [threading.Thread(target=send, args=(number,)) for number in numbers]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return time.monotonic() - started, failures

    def test_items_are_sent_together_up_to_the_limit_and_all_are_logged(self):
        fm = Slow()
        dispatcher = Dispatcher(self.path, fm, "57")
        numbers = [chr(65 + i) for i in range(12)]
        elapsed, failures = self.send_together(dispatcher, numbers)
        self.assertEqual(failures, [])
        self.assertGreater(fm.most, 1)
        self.assertLessEqual(fm.most, WRITES)
        self.assertLess(elapsed, LATENCY * len(numbers) * 0.6)   # one after the other it would be 12 latencies
        self.assertEqual(sorted(logged(self.path)), sorted("item:" + n for n in numbers))
        self.assertTrue(all(dispatcher._ids[n.casefold()] for n in numbers))

    def test_a_slow_item_does_not_hold_up_the_others(self):
        hold = threading.Event()
        fm = Slow(hold=hold)
        dispatcher = Dispatcher(self.path, fm, "57")
        slow = threading.Thread(target=lambda: dispatcher.send_item("A", create("A")))
        slow.start()
        while fm.under_way == 0:
            time.sleep(0.005)
        dispatcher.send_item("B", create("B"))   # goes through while A is still being answered
        self.assertNotIn("in_doubt", logged(self.path)["item:B"])
        self.assertEqual(logged(self.path)["item:A"], {"in_doubt": True})   # still being answered: logged as about to be sent, not as done
        hold.set()
        slow.join()
        self.assertEqual(sorted(logged(self.path)), ["item:A", "item:B"])
        self.assertNotIn("in_doubt", logged(self.path)["item:A"])

    def test_an_item_that_is_refused_does_not_stop_the_ones_sent_with_it(self):
        fm = Slow(refuse="?bad")
        dispatcher = Dispatcher(self.path, fm, "57")
        threads, failures = [], []

        def send(number, request):
            try:
                dispatcher.send_item(number, request)
            except FmApiError as exc:
                failures.append(number)

        requests = {"A": create("A"), "B": {"method": "POST", "url": "/api/v3/workspaces/57/items?bad", "body": {"n": "B"}}, "C": create("C")}
        for number, request in requests.items():
            threads.append(threading.Thread(target=send, args=(number, request)))
            threads[-1].start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, ["B"])
        self.assertEqual(sorted(logged(self.path)), ["item:A", "item:C"])
        self.assertIn("b", dispatcher._failed)


class SendRunParallelTests(unittest.TestCase):
    def test_a_folder_sent_again_sends_its_items_together(self):
        numbers = [chr(65 + i) for i in range(10)]
        with tempfile.TemporaryDirectory() as root:
            write_folder(root, {n: create(n) for n in numbers}, {})
            fm = Slow()
            run = SendRun(root, load_plan(root), fm)
            started = time.monotonic()
            run.work()
            elapsed = time.monotonic() - started
            self.assertEqual(run.phase, DONE)
            self.assertEqual([row["status"] for row in run.rows], [DONE] * 10)
            self.assertEqual((run.done, run.total), (10, 10))
            self.assertGreater(fm.most, 1)
            self.assertLessEqual(fm.most, WRITES)
            self.assertLess(elapsed, LATENCY * len(numbers) * 0.6)
            self.assertEqual(len(logged(root)), 10)

    def test_a_run_cancelled_before_it_starts_sends_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            write_folder(root, {"A": create("A"), "B": create("B")}, {})
            fm = Slow()
            run = SendRun(root, load_plan(root), fm)
            run.cancel()
            run.work()
            self.assertEqual(fm.sent, [])


if __name__ == "__main__":
    unittest.main()
