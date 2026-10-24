"""The runs a progress dialog is following, so the message box that tells a run ended is not shown on top of it.

The Publish panel's dialog asks for the runs every second and names the one it follows. A run that was asked for within
``SECONDS`` is being watched; a dialog that was closed (or a panel that went away) stops asking, and the run is reported by
the message box after all.
"""

import time
from typing import Callable, Dict

SECONDS = 5.0   # a dialog that has not asked for this long is gone


class Watched:
    def __init__(self, seconds: float = SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._seconds, self._clock = seconds, clock
        self._seen: Dict[str, float] = {}   # run id -> when a dialog last asked for it

    def touch(self, run_id: str) -> None:
        """A dialog is following the run."""
        if run_id:
            self._seen[run_id] = self._clock()

    def following(self, run_id: str) -> bool:
        """Whether a dialog is following the run now."""
        seen = self._seen.get(run_id)
        return seen is not None and self._clock() - seen <= self._seconds
