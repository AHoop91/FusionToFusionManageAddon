"""A lap is the time since the last lap, so the laps of a job add up to its whole time."""

import unittest
from unittest import mock

from src.core import timing
from src.core.timing import Stopwatch


class StopwatchTests(unittest.TestCase):
    def test_each_lap_starts_where_the_last_ended(self):
        with mock.patch.object(timing.time, "monotonic", side_effect=[10.0, 12.5, 13.0]):
            watch = Stopwatch()
            self.assertEqual(watch.lap(), 2.5)
            self.assertEqual(watch.lap(), 0.5)


if __name__ == "__main__":
    unittest.main()
