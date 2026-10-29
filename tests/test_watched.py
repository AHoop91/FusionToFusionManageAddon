"""The runs a progress dialog is following."""

import threading
import unittest

from src.publish.watched import Watched


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class WatchedTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.watched = Watched(seconds=5, clock=self.clock)

    def test_a_run_nobody_asked_for_is_not_watched(self):
        self.assertFalse(self.watched.following("a"))

    def test_a_run_a_dialog_just_asked_for_is_watched(self):
        self.watched.touch("a")
        self.clock.now += 4
        self.assertTrue(self.watched.following("a"))
        self.assertFalse(self.watched.following("b"))

    def test_a_dialog_that_stopped_asking_is_gone(self):
        self.watched.touch("a")
        self.clock.now += 6
        self.assertFalse(self.watched.following("a"))

    def test_asking_again_keeps_it_watched(self):
        self.watched.touch("a")
        self.clock.now += 4
        self.watched.touch("a")
        self.clock.now += 4
        self.assertTrue(self.watched.following("a"))

    def test_an_empty_id_is_never_watched(self):
        self.watched.touch("")
        self.assertFalse(self.watched.following(""))

    def test_a_run_is_watched_for_less_than_the_time_and_not_at_it(self):
        self.watched.touch("a")
        self.clock.now += 4.9
        self.assertTrue(self.watched.following("a"))
        self.clock.now += 0.1
        self.assertFalse(self.watched.following("a"))

    def test_runs_that_are_no_longer_asked_for_are_forgotten_not_kept(self):
        for number in range(1000):   # one run after another over a long session, each asked for a few times and then left
            self.watched.touch(f"run-{number}")
            self.clock.now += 6
        self.assertLess(len(self.watched._seen._entries), 300)

    def test_it_can_be_asked_and_told_from_several_threads_at_once(self):
        clock, failures = [0.0], []

        def work(name):
            try:
                for number in range(2000):
                    self.watched.touch(f"{name}-{number}")
                    self.watched.following(f"{name}-{number - 1}")
                    clock[0] += 0.01
            except Exception as exc:   # a dictionary changed under a sweep, say
                failures.append(exc)

        watched = Watched(seconds=1, clock=lambda: clock[0])
        self.watched = watched
        threads = [threading.Thread(target=work, args=(name,)) for name in "abcd"]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
