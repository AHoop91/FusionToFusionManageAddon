"""Elapsed time for the log."""

import time


class Stopwatch:
    """Times the steps of a job: ``lap()`` is the seconds since the last lap (or since the stopwatch was made) and starts the next."""

    def __init__(self) -> None:
        self._mark = time.monotonic()

    def lap(self) -> float:
        now = time.monotonic()
        seconds, self._mark = now - self._mark, now
        return seconds
