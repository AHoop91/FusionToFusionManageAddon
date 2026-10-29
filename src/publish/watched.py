"""The runs a progress dialog is following, so the message box that tells a run ended is not shown on top of it.

The Publish panel's dialog asks for the runs every second and names the one it follows. A run that was asked for within
``SECONDS`` is being watched; a dialog that was closed (or a panel that went away) stops asking, and the run is reported by
the message box after all.
"""

import time
from typing import Callable

from ..fm.ttl_cache import TtlCache

SECONDS = 5.0   # a dialog that has not asked for this long is gone


class Watched:
    """Which runs a dialog is following. ``touch`` is called from the thread that answers the panel, ``following`` from the queue's worker
    thread when a run ends; a run asked for long ago is forgotten, so the runs of a long session do not pile up."""

    def __init__(self, seconds: float = SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._seen = TtlCache(seconds, clock)   # run id -> True, for as long as a dialog's last ask counts

    def touch(self, run_id: str) -> None:
        """A dialog is following the run (nothing for an empty id: a dialog that follows no run)."""
        if run_id:
            self._seen.put(run_id, True)

    def following(self, run_id: str) -> bool:
        """Whether a dialog asked for the run less than ``SECONDS`` ago."""
        return self._seen.get(run_id) is not None
