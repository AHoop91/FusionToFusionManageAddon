"""The queue of publish runs: a run that ended clean stays until the next one is added."""

import threading
import unittest

from src.publish.job_queue import JobQueue
from src.publish.job_state import JobState
from src.publish.states import DONE, ERROR


class Run(JobState):
    """A run that finishes at once, with its one row ``done`` or ``error``."""

    def __init__(self, name, outcome=DONE):
        super().__init__(name, "folder")
        self.outcome = outcome
        self.ended = threading.Event()
        self.rows = [self.row(name, "")]

    def work(self):
        self._start()
        self.rows[0]["status"] = "done" if self.outcome == DONE else "error"
        self._finish(self.outcome, "")

    def _finish(self, phase, message):
        self._end(phase, message)
        self.ended.set()


def names(queue):
    return [s["name"] for s in queue.snapshots()]


class JobQueueTests(unittest.TestCase):
    def finish(self, queue, run):
        queue.add(run)
        self.assertTrue(run.ended.wait(5))
        for _ in range(250):   # the worker thread is still leaving the queue
            if queue._worker is None:
                break
            threading.Event().wait(0.02)

    def test_a_run_that_ended_clean_is_still_listed_so_the_panel_can_read_how_it_ended(self):
        queue = JobQueue()
        self.finish(queue, Run("A"))
        self.assertEqual(names(queue), ["A"])
        self.assertEqual(queue.snapshots()[0]["phase"], DONE)

    def test_it_is_forgotten_when_the_next_run_is_added(self):
        queue = JobQueue()
        self.finish(queue, Run("A"))
        self.finish(queue, Run("B"))
        self.assertEqual(names(queue), ["B"])

    def test_a_failed_run_stays_until_it_is_cleared(self):
        queue = JobQueue()
        self.finish(queue, Run("A", ERROR))
        self.finish(queue, Run("B"))
        self.assertEqual(names(queue), ["A", "B"])
        queue.clear_finished()
        self.assertEqual(names(queue), [])


if __name__ == "__main__":
    unittest.main()
