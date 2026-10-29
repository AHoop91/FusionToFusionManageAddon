"""Running work off Fusion's thread. Run: python -m unittest discover tests"""

import threading
import unittest
from unittest import mock

from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import background
    from src.ui.actions.background import THREAD_NAME, BackgroundRead, in_thread, why

WAIT_SECONDS = 5


class InThreadTests(unittest.TestCase):
    def test_the_work_runs_on_another_thread_that_is_named_and_a_daemon(self):
        seen, finished = [], threading.Event()

        def work():
            seen.append(threading.current_thread())
            finished.set()

        in_thread(work)
        self.assertTrue(finished.wait(WAIT_SECONDS))
        self.assertIsNot(seen[0], threading.main_thread())
        self.assertEqual(seen[0].name, THREAD_NAME)
        self.assertTrue(seen[0].daemon)

    def test_work_that_raises_is_logged_and_does_not_end_up_on_the_console(self):
        logged = threading.Event()

        def fail():
            raise RuntimeError("boom")

        with mock.patch.object(background, "log") as log:
            log.exception.side_effect = lambda *args: logged.set()
            in_thread(fail)
            self.assertTrue(logged.wait(WAIT_SECONDS))
        log.exception.assert_called_once_with("Background work failed")


class WhyTests(unittest.TestCase):
    def test_a_failure_is_told_by_its_message_or_else_by_its_kind(self):
        self.assertEqual(why(ValueError("no good")), "no good")
        self.assertEqual(why(RuntimeError()), "RuntimeError")


class BackgroundReadTests(unittest.TestCase):
    def setUp(self):
        self.bridge = mock.Mock()
        self.queued = []   # the reads, run by the test when it wants them to finish
        self.read = BackgroundRead(self.bridge, "act", {"things": []}, run=self.queued.append)

    def finish(self):
        while self.queued:
            self.queued.pop(0)()

    @staticmethod
    def preparing(**found):
        return lambda: (lambda: found)

    def test_before_any_read_the_status_is_blank(self):
        self.assertEqual(self.read.status(), {"pending": False, "ok": False, "message": "", "things": []})

    def test_a_start_answers_pending_and_the_outcome_is_pushed_when_done(self):
        self.assertEqual(self.read.start(self.preparing(things=[1])), {"pending": True, "ok": False, "message": "", "things": []})
        self.finish()
        done = {"pending": False, "ok": True, "message": "", "things": [1]}
        self.bridge.push.assert_called_once_with("act", done)
        self.assertEqual(self.read.status(), done)

    def test_the_work_may_say_it_was_not_ok_and_why(self):
        self.read.start(self.preparing(ok=False, message="not linked"))
        self.finish()
        self.assertEqual((self.read.status()["ok"], self.read.status()["message"]), (False, "not linked"))
        self.assertFalse(self.read.status()["pending"])

    def test_asking_while_it_is_read_answers_how_it_stands_and_starts_no_second_read(self):
        self.read.start(self.preparing())
        prepare = mock.Mock()
        self.assertEqual(self.read.start(prepare)["pending"], True)
        prepare.assert_not_called()
        self.assertEqual(len(self.queued), 1)

    def test_a_read_can_be_started_again_once_it_is_done(self):
        self.read.start(self.preparing(things=[1]))
        self.finish()
        self.assertEqual(self.read.start(self.preparing(things=[2]))["things"], [])   # the old answer is not shown as the new one
        self.finish()
        self.assertEqual(self.read.status()["things"], [2])

    def test_a_failing_read_is_told_as_a_failure_with_why_and_nothing_found(self):
        def fail():
            raise ValueError("no good")

        self.read.start(lambda: fail)
        self.finish()
        failed = {"pending": False, "ok": False, "message": "no good", "things": []}
        self.bridge.push.assert_called_once_with("act", failed)
        self.assertEqual(self.read.status(), failed)

    def test_a_prepare_that_raises_starts_nothing_and_leaves_the_status_alone(self):
        def refuse():
            raise RuntimeError("no hub")

        with self.assertRaises(RuntimeError):
            self.read.start(refuse)
        self.assertEqual(self.queued, [])
        self.assertFalse(self.read.status()["pending"])
        self.read.start(self.preparing())   # not stuck pending
        self.assertEqual(len(self.queued), 1)

    def test_a_failure_to_start_is_the_blank_outcome_with_the_reason_and_is_not_kept(self):
        self.assertEqual(self.read.failure("why not"), {"pending": False, "ok": False, "message": "why not", "things": []})
        self.assertEqual(self.read.status()["message"], "")

    def test_many_threads_asking_at_once_start_one_read(self):
        asked = threading.Barrier(20)
        prepared = []

        def prepare():
            prepared.append(1)
            return lambda: {}

        def ask():
            asked.wait(WAIT_SECONDS)   # all at the same moment
            self.read.start(prepare)

        threads = [threading.Thread(target=ask, daemon=True) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(WAIT_SECONDS)
        self.assertEqual((len(prepared), len(self.queued)), (1, 1))

    def test_a_status_asked_while_a_read_finishes_is_never_half_written(self):
        read = BackgroundRead(self.bridge, "act", {"things": []}, run=lambda work: work())
        seen, stop = [], threading.Event()

        def watch():
            while not stop.is_set():
                seen.append(read.status())

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        for number in range(200):
            read.start(self.preparing(things=[number]))
        stop.set()
        watcher.join(WAIT_SECONDS)
        self.assertTrue(seen)
        for state in seen:
            self.assertEqual(set(state), {"pending", "ok", "message", "things"})
            if state["pending"]:   # a read under way shows nothing found yet, never a mix of the old answer and the new state
                self.assertEqual((state["ok"], state["things"]), (False, []))

    def test_a_runner_that_does_the_work_at_once_does_not_deadlock(self):
        read = BackgroundRead(self.bridge, "act", run=lambda work: work())
        done = []
        thread = threading.Thread(target=lambda: done.append(read.start(self.preparing(a=1))), daemon=True)
        thread.start()
        thread.join(WAIT_SECONDS)
        self.assertEqual(len(done), 1)
        self.assertEqual(read.status()["a"], 1)


if __name__ == "__main__":
    unittest.main()
