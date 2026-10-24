"""The runs a progress dialog is following."""

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


if __name__ == "__main__":
    unittest.main()
