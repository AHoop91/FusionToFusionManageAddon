"""The queue of publish runs: a run that ended clean stays until the next one is added."""

import os
import shutil
import tempfile
import threading
import unittest

from src.publish.job_queue import JobQueue
from src.publish.job_state import JobState
from src.publish.states import CANCELLED, DONE, ERROR


class Run(JobState):
    """A run that finishes at once, with its one row ``done`` or ``error``; ``unlisted`` is a run that stopped before writing anything."""

    def __init__(self, name, outcome=DONE, unlisted=False, folder="folder"):
        super().__init__(name, folder)
        self.outcome = outcome
        self.stopped_early = unlisted
        self.ended = threading.Event()
        self.rows = [self.row(name, "")]

    def work(self):
        self._start()
        self.rows[0]["status"] = "done" if self.outcome == DONE else "error"
        self._finish(self.outcome, "")

    @property
    def unlisted(self):
        return self.stopped_early

    def _finish(self, phase, message):
        self._end(phase, message)
        self.ended.set()


class Crashing(Run):
    """A run whose ``work`` raises: after it started, or before."""

    def __init__(self, name, after_start=True):
        super().__init__(name)
        self.after_start = after_start

    def work(self):
        if self.after_start:
            self._start()
        raise RuntimeError("boom")


class Blocked(Run):
    """A run that works until it is let go."""

    def __init__(self, name):
        super().__init__(name)
        self.started, self.go = threading.Event(), threading.Event()

    def work(self):
        self._start()
        self.started.set()
        self.go.wait(5)
        super().work()


def names(queue):
    return [s["name"] for s in queue.snapshots()]


class JobQueueTests(unittest.TestCase):
    def finish(self, queue, run):
        queue.add(run)
        self.assertTrue(run.ended.wait(5))
        queue.join(5)   # the worker thread is still leaving the queue

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

    def files_root(self):
        """A root for the run folders, as the queue is given one in the add-in."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def folder(self, root):
        path = os.path.join(root, "PN-1_20260101-000000")
        os.makedirs(path)
        with open(os.path.join(path, "manifest.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        return path

    def test_the_files_of_a_run_that_ended_clean_are_removed(self):
        root = self.files_root()
        path = self.folder(root)
        self.finish(JobQueue(files_root=root), Run("A", folder=path))
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.isdir(root))   # only the run's folder goes

    def test_the_files_of_a_failed_run_are_kept_for_retry(self):
        root = self.files_root()
        path = self.folder(root)
        self.finish(JobQueue(files_root=root), Run("A", ERROR, folder=path))
        self.assertTrue(os.path.exists(path))

    def test_clearing_a_failed_run_removes_its_files(self):
        root = self.files_root()
        path = self.folder(root)
        queue = JobQueue(files_root=root)
        self.finish(queue, Run("A", ERROR, folder=path))
        queue.clear_finished()
        self.assertFalse(os.path.exists(path))

    def test_a_folder_outside_the_root_is_never_removed(self):
        root, elsewhere = self.files_root(), self.files_root()
        path = self.folder(elsewhere)
        self.finish(JobQueue(files_root=root), Run("A", folder=path))
        self.assertTrue(os.path.exists(path))

    def test_without_a_root_nothing_is_removed(self):
        root = self.files_root()
        path = self.folder(root)
        self.finish(JobQueue(), Run("A", folder=path))
        self.assertTrue(os.path.exists(path))

    def test_a_failed_run_stays_until_it_is_cleared(self):
        queue = JobQueue()
        self.finish(queue, Run("A", ERROR))
        self.finish(queue, Run("B"))
        self.assertEqual(names(queue), ["A", "B"])
        queue.clear_finished()
        self.assertEqual(names(queue), [])

    def test_a_run_that_stopped_before_writing_does_not_turn_the_queue_to_error_and_is_forgotten_at_the_next_run(self):
        queue = JobQueue()
        self.finish(queue, Run("A", ERROR, unlisted=True))
        self.assertEqual(queue.state(), "idle")
        self.assertEqual(names(queue), ["A"])   # the panel that queued it still reads how it ended
        self.finish(queue, Run("B"))
        self.assertEqual(names(queue), ["B"])

    def test_a_run_that_crashes_is_ended_as_an_error_and_the_queue_goes_on(self):
        for after_start in (True, False):
            with self.subTest(after_start=after_start):
                queue, crashing = JobQueue(), Crashing("A", after_start)
                self.finish(queue, crashing)   # a run left queued would be taken again and again: this would not end
                self.assertEqual(crashing.phase, ERROR)
                self.assertIn("boom", crashing.message)
                self.assertEqual(queue.state(), "error")
                self.finish(queue, Run("B"))
                self.assertEqual(names(queue), ["A", "B"])

    def test_a_run_whose_own_ending_fails_is_still_ended(self):
        run = Run("A")
        run._finish = lambda phase, message: (_ for _ in ()).throw(OSError("disk full"))
        run.crashed("stopped")
        self.assertEqual((run.phase, run.message), (ERROR, "stopped"))

    def test_a_crash_does_not_overwrite_how_a_run_ended(self):
        run = Run("A")
        run.work()
        run.crashed("late")
        self.assertEqual((run.phase, run.message), (DONE, ""))

    def test_a_waiting_run_says_its_place_and_cancelling_it_means_it_never_starts(self):
        queue, first, second, third = JobQueue(), Blocked("A"), Run("B"), Run("C")
        queue.add(first)
        self.assertTrue(first.started.wait(5))
        queue.add(second)
        queue.add(third)
        self.assertEqual([(s["name"], s.get("place")) for s in queue.snapshots()], [("A", None), ("B", 1), ("C", 2)])
        self.assertEqual(queue.state(), "running")
        queue.cancel(second.id)
        queue.cancel("not-a-run")   # nothing listed under that id
        first.go.set()
        self.assertTrue(third.ended.wait(5))
        self.assertEqual((second.phase, second.rows[0]["status"]), (CANCELLED, CANCELLED))

    def test_a_retry_takes_the_place_of_the_failed_run_it_replaces(self):
        queue, failed = JobQueue(), Run("A", ERROR)
        self.finish(queue, failed)
        self.finish(queue, Run("B", ERROR))
        retry = Run("A again")
        queue.replace(failed, retry)
        self.assertTrue(retry.ended.wait(5))
        self.assertEqual(names(queue), ["B", "A again"])

    def test_a_failing_notification_does_not_stop_the_queue(self):
        def explode(*_):
            raise RuntimeError("no")

        queue = JobQueue(on_change=explode, on_finished=explode)
        self.finish(queue, Run("A"))
        self.finish(queue, Run("B"))
        self.assertEqual(names(queue), ["B"])

    def test_it_tells_when_a_run_ended(self):
        ended = []
        queue = JobQueue(on_finished=ended.append)
        run = Run("A")
        self.finish(queue, run)
        self.assertEqual(ended, [run])

    def test_a_failed_row_in_a_finished_run_makes_the_queue_error(self):
        queue = JobQueue()
        run = Run("A")
        self.finish(queue, run)
        self.assertEqual(queue.state(), "idle")
        run.rows[0]["status"] = ERROR
        self.assertEqual(queue.state(), "error")


if __name__ == "__main__":
    unittest.main()
